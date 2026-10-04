# =============================================================================
# SemanticWindowPlanner — ventanas por capacidad real, no por constante
# =============================================================================
# `chunk_size = X / overlap = Y` no decide una ventana semántica. El planner
# deriva el presupuesto de:
#
#   capacidad real del modelo (registry, nunca hardcode)
#   + reservas (salida/sistema/seguridad)
#   + perfil de calidad (economy/balanced/quality/maximum_quality)
#   + estructura y densidad de la fuente (tablas, código, bloques grandes)
#
# Límites SOFT: una unidad semántica que cruza el objetivo entra completa
# dentro del headroom; el HARD limit solo actúa cuando la unidad no cabe ni
# con headroom. Si un bloque completo excede el hard limit, el planner lo
# parte en piezas con char offsets (la ventana sigue siendo procesable).
# Sin LLM, determinista y auditable.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from src.core.domain.knowledge_v2 import (
    StructuredBlock,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure.base import token_count
from src.rag.longcontext.registry import resolve_model_capability

from .contracts import WINDOW_PLAN_VERSION, SemanticWindowPlan, SemanticWindowSpec

#: (fracción del usable, techo por perfil). El resultado se ajusta por densidad.
_PROFILE_POLICY: dict[str, tuple[float, int]] = {
    "economy": (0.35, 16_000),
    "balanced": (0.55, 32_000),
    "quality": (0.75, 64_000),
    "maximum_quality": (1.0, 96_000),
}

_SKIP_KINDS = {
    StructuredBlockKind.HEADER,
    StructuredBlockKind.FOOTER,
    StructuredBlockKind.PAGE_NUMBER,
}

#: Tope de piezas al partir un bloque mayor que el hard limit (anti-explosión).
_MAX_SPLIT_PIECES = 10_000


def _settings():
    try:
        from src.core.config import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001 — sin settings, defaults conservadores
        return None


def _setting(name: str, default):
    settings = _settings()
    if settings is None:
        return default
    return getattr(settings, name, default)


def _parse_model_windows(raw: str) -> dict[str, int]:
    """Override de ventanas por modelo: JSON {"modelo": tokens}. Config manda."""
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    windows: dict[str, int] = {}
    for key, value in payload.items():
        try:
            window = int(value)
        except (TypeError, ValueError):
            continue
        if window > 0:
            windows[str(key).strip().lower()] = window
    return windows


def is_indexable_block(block: StructuredBlock) -> bool:
    if block.metadata.get("chrome") or block.metadata.get("superseded"):
        return False
    if block.metadata.get("index_semantic") is False:
        return False
    return block.kind not in _SKIP_KINDS


#: Compatibilidad con llamadores previos (tests y código interno).
_is_indexable = is_indexable_block


def indexable_blocks(document: StructuredDocument) -> list[StructuredBlock]:
    """Bloques en orden de lectura que participan de la comprensión/índice."""
    return [block for block in document.blocks if is_indexable_block(block)]


@dataclass(frozen=True, kw_only=True)
class WindowBudget:
    """Presupuesto resuelto del planner (auditado en el plan)."""

    model: str
    model_source: str
    context_window: int
    hard_limit_tokens: int
    target_tokens: int
    profile: str
    headroom_ratio: float
    min_tokens: int
    notes: dict


@dataclass(frozen=True, kw_only=True)
class _PlanUnit:
    """Pieza procesable de un bloque (un bloque chico = una pieza)."""

    block_id: UUID | None
    block_index: int
    tokens: int
    char_start: int | None = None
    char_end: int | None = None


class SemanticWindowPlanner:
    """Decide ventanas semánticas soft para una fuente ya estructurada."""

    version = WINDOW_PLAN_VERSION

    def plan(
        self,
        document: StructuredDocument,
        *,
        profile: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        min_tokens: int | None = None,
        headroom_ratio: float | None = None,
        reserves: int | None = None,
    ) -> SemanticWindowPlan:
        blocks = [block for block in document.blocks if is_indexable_block(block)]
        profile_name = str(
            profile
            or _setting("KNOWLEDGE_SEMANTIC_INGESTION_PROFILE", "balanced")
            or "balanced"
        ).strip().lower()
        if profile_name not in _PROFILE_POLICY:
            profile_name = "balanced"

        budget = self._budget(
            document,
            profile=profile_name,
            model=model,
            max_tokens=max_tokens,
            min_tokens=min_tokens,
            headroom_ratio=headroom_ratio,
            reserves=reserves,
        )
        if not blocks:
            return SemanticWindowPlan(
                document_id=str(document.id),
                model=budget.model,
                model_source=budget.model_source,
                profile=budget.profile,
                hard_limit_tokens=budget.hard_limit_tokens,
                target_tokens=budget.target_tokens,
                notes={**budget.notes, "empty": True},
            )

        units, block_spans = self._plan_units(blocks, budget.hard_limit_tokens)
        tokens = [max(1, unit.tokens) for unit in units]
        prefix = [0]
        for value in tokens:
            prefix.append(prefix[-1] + value)
        total_tokens = prefix[-1]

        atomic = self._atomic_ranges(document, blocks, block_spans)
        unit_start_at = [None] * len(units)
        unit_end_at = [None] * len(units)
        for start, end in atomic:
            for position in range(start, end + 1):
                if unit_start_at[position] is None or start > unit_start_at[position]:
                    unit_start_at[position] = start
                if unit_end_at[position] is None or end > unit_end_at[position]:
                    unit_end_at[position] = end

        windows: list[SemanticWindowSpec] = []
        preserved = 0
        splits = 0
        position = 0
        while position < len(units):
            start = position
            end = start
            # Avanza mientras el bloque completo quepa en el objetivo.
            while end < len(units):
                candidate = prefix[end + 1] - prefix[start]
                if end > start and candidate > budget.target_tokens:
                    break
                end += 1
            end -= 1  # última posición incluida
            boundary = end + 1
            crossing_end = unit_end_at[boundary] if boundary < len(units) else None
            crossing_start = unit_start_at[boundary] if boundary < len(units) else None
            window_reason = "target_reached"
            window_preserved = 0
            window_splits = 0
            if (
                crossing_end is not None
                and crossing_start is not None
                and crossing_start <= end
            ):
                # El corte cae DENTRO de una unidad semántica: extenderla entera
                # si el resultado cabe en el headroom (soft limit de verdad).
                unit_tokens = prefix[crossing_end + 1] - prefix[crossing_start]
                extended = prefix[crossing_end + 1] - prefix[start]
                headroom = int(budget.target_tokens * (1.0 + budget.headroom_ratio))
                if extended <= headroom:
                    end = crossing_end
                    boundary = end + 1
                    window_preserved = 1
                    window_reason = "soft_boundary_preserved"
                elif crossing_start > start:
                    end = crossing_start - 1
                    boundary = end + 1
                    window_reason = "soft_boundary_before_unit"
                elif unit_tokens <= budget.hard_limit_tokens:
                    end = crossing_end
                    boundary = end + 1
                    window_preserved = 1
                    window_reason = "hard_limit_preserved_unit"
                else:
                    # Unidad mayor que el hard limit: partición inevitable.
                    fit = self._fit_hard(prefix, start, budget.hard_limit_tokens)
                    if fit <= start:
                        fit = start + 1
                    end = fit - 1
                    boundary = end + 1
                    window_splits = 1
                    window_reason = "unit_exceeds_hard_limit"
            if boundary <= start:
                boundary = start + 1
                end = start
            window_tokens = prefix[end + 1] - prefix[start]
            first_unit = units[start]
            last_unit = units[end]
            windows.append(
                SemanticWindowSpec(
                    window_index=len(windows),
                    unit_start=start,
                    unit_end=end,
                    estimated_tokens=window_tokens,
                    target_tokens=budget.target_tokens,
                    hard_limit_tokens=budget.hard_limit_tokens,
                    first_block_id=first_unit.block_id,
                    last_block_id=last_unit.block_id,
                    char_start=first_unit.char_start,
                    char_end=last_unit.char_end,
                    preserved_units=window_preserved,
                    split_units=window_splits,
                    status="planned",
                    reason=window_reason,
                )
            )
            preserved += window_preserved
            splits += window_splits
            position = boundary

        return SemanticWindowPlan(
            document_id=str(document.id),
            model=budget.model,
            model_source=budget.model_source,
            profile=budget.profile,
            hard_limit_tokens=budget.hard_limit_tokens,
            target_tokens=budget.target_tokens,
            total_units=len(units),
            total_tokens=total_tokens,
            soft_extensions=preserved,
            split_units=splits,
            windows=tuple(windows),
            notes={**budget.notes, "atomic_units": len(atomic)},
        )

    # ------------------------------------------------------------------
    # Presupuesto
    # ------------------------------------------------------------------
    def _budget(
        self,
        document: StructuredDocument,
        *,
        profile: str,
        model: str | None,
        max_tokens: int | None,
        min_tokens: int | None = None,
        headroom_ratio: float | None = None,
        reserves: int | None = None,
    ) -> WindowBudget:
        model_name = str(
            model
            or _setting("KNOWLEDGE_SEMANTIC_INGESTION_MODEL", "")
            or _setting("KNOWLEDGE_SUMMARY_MODEL", "")
            or ""
        ).strip()
        overrides = _parse_model_windows(
            str(_setting("RAG_MODEL_CONTEXT_WINDOWS", "") or "")
        )
        default_window = int(
            _setting("RAG_MODEL_DEFAULT_CONTEXT_WINDOW", 32_000) or 32_000
        )
        capability = resolve_model_capability(
            model_name,
            overrides=overrides,
            default_window=default_window,
        )
        configured_max = int(
            _setting("KNOWLEDGE_SEMANTIC_WINDOW_MAX_TOKENS", 0) or 0
        )
        if max_tokens and int(max_tokens) > 0:
            configured_max = int(max_tokens)
        hard_cap = capability.context_window
        if configured_max > 0:
            hard_cap = min(hard_cap, configured_max)
        hard_cap = max(1, hard_cap)

        reserves_total = reserves
        if reserves_total is None:
            reserves_total = (
                int(_setting("KNOWLEDGE_SEMANTIC_WINDOW_OUTPUT_RESERVE", 2048) or 0)
                + int(_setting("KNOWLEDGE_SEMANTIC_WINDOW_SYSTEM_RESERVE", 1500) or 0)
                + int(_setting("KNOWLEDGE_SEMANTIC_WINDOW_SAFETY_RESERVE", 1000) or 0)
            )
        reserves_total = max(0, int(reserves_total))
        floor_tokens = max(
            1,
            int(
                min_tokens
                if min_tokens is not None
                else _setting("KNOWLEDGE_SEMANTIC_WINDOW_MIN_TOKENS", 2000) or 2000
            ),
        )
        floor_tokens = min(floor_tokens, hard_cap)
        hard_limit = min(hard_cap, max(floor_tokens, hard_cap - reserves_total))
        fraction, ceiling = _PROFILE_POLICY[profile]
        base = min(ceiling, int(hard_limit * fraction))

        table_ratio, code_ratio, avg_tokens = _density(document)
        factor = 1.0
        notes: dict = {
            "table_ratio": round(table_ratio, 4),
            "code_ratio": round(code_ratio, 4),
            "avg_block_tokens": round(avg_tokens, 2),
            "reserves_tokens": reserves_total,
            "profile_fraction": fraction,
            "profile_ceiling": ceiling,
        }
        if table_ratio > 0.30:
            factor *= 0.80
            notes["table_penalty"] = 0.80
        if code_ratio > 0.20:
            factor *= 0.85
            notes["code_penalty"] = 0.85
        if avg_tokens > 220:
            factor *= 1.15
            notes["large_block_bonus"] = 1.15
        target = int(base * factor)
        target = max(floor_tokens, min(target, hard_limit))
        notes["hard_limit_source"] = capability.source
        headroom = (
            max(0.0, float(headroom_ratio))
            if headroom_ratio is not None
            else max(
                0.0,
                float(
                    _setting("KNOWLEDGE_SEMANTIC_WINDOW_HEADROOM_RATIO", 0.20) or 0.0
                ),
            )
        )
        return WindowBudget(
            model=capability.model_name,
            model_source=capability.source,
            context_window=capability.context_window,
            hard_limit_tokens=hard_limit,
            target_tokens=target,
            profile=profile,
            headroom_ratio=headroom,
            min_tokens=floor_tokens,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Unidades de plan (bloques + split de bloques gigantes)
    # ------------------------------------------------------------------
    @staticmethod
    def _plan_units(
        blocks: list[StructuredBlock], hard_limit: int
    ) -> tuple[list[_PlanUnit], dict[int, tuple[int, int]]]:
        units: list[_PlanUnit] = []
        spans: dict[int, tuple[int, int]] = {}
        for index, block in enumerate(blocks):
            first = len(units)
            text = block.text or ""
            tokens = max(1, token_count(text))
            if tokens <= hard_limit or not text.strip():
                units.append(
                    _PlanUnit(block_id=block.id, block_index=index, tokens=tokens)
                )
            else:
                pieces = _split_text_pieces(text, hard_limit)
                for char_start, char_end in pieces[:_MAX_SPLIT_PIECES]:
                    piece_text = text[char_start:char_end]
                    units.append(
                        _PlanUnit(
                            block_id=block.id,
                            block_index=index,
                            tokens=max(1, token_count(piece_text)),
                            char_start=char_start,
                            char_end=char_end,
                        )
                    )
            spans[index] = (first, len(units) - 1)
        return units, spans

    def _atomic_ranges(
        self,
        document: StructuredDocument,
        blocks: list[StructuredBlock],
        block_spans: dict[int, tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Rangos de plan-unit de unidades semánticas (nunca partir una)."""
        position = {block.id: index for index, block in enumerate(blocks)}

        def to_plan_span(source_start: int, source_end: int) -> tuple[int, int] | None:
            first = block_spans.get(source_start)
            last = block_spans.get(source_end)
            if first is None or last is None:
                return None
            return (first[0], last[1])

        try:
            from src.knowledge.understanding.units import build_retrieval_units

            budget = int(_setting("SEMANTIC_UNIT_MAX_CHARS", 1200) or 1200)
            retrieval_units = build_retrieval_units(document, budget=budget)
        except Exception:  # noqa: BLE001 — sin unidades, cada bloque es atómico
            return [
                span
                for _index, span in sorted(block_spans.items())
                if span[0] <= span[1]
            ]
        ranges: list[tuple[int, int]] = []
        for unit in retrieval_units:
            if unit.unit_type == "SECTION":
                continue
            indexes = []
            for raw in unit.block_ids:
                try:
                    block_id = UUID(str(raw))
                except (TypeError, ValueError):
                    continue
                if block_id in position:
                    indexes.append(position[block_id])
            if not indexes:
                continue
            span = to_plan_span(min(indexes), max(indexes))
            if span is not None:
                ranges.append(span)
        if not ranges:
            # Fallback: cada bloque es atómico (rangos por span de bloque).
            return [
                span
                for _index, span in sorted(block_spans.items())
                if span[0] <= span[1]
            ]
        return ranges

    @staticmethod
    def _fit_hard(prefix: list[int], start: int, hard_limit: int) -> int:
        """Primer índice exclusivo que no supera el hard limit desde `start`."""
        end = start
        while end + 1 < len(prefix) and prefix[end + 1] - prefix[start] <= hard_limit:
            end += 1
        return max(end, start + 1)


def _split_text_pieces(text: str, hard_limit: int) -> list[tuple[int, int]]:
    """Parte texto por palabras en tramos <= hard_limit tokens (char offsets)."""
    words = text.split()
    if not words:
        return [(0, len(text))]
    offsets: list[int] = []
    cursor = 0
    for word in words:
        found = text.find(word, cursor)
        if found < 0:
            found = cursor
        offsets.append(found)
        cursor = found + len(word)
    pieces: list[tuple[int, int]] = []
    start_word = 0
    while start_word < len(words):
        end_word = min(len(words), start_word + max(1, hard_limit))
        char_start = offsets[start_word]
        char_end = offsets[end_word - 1] + len(words[end_word - 1])
        pieces.append((char_start, char_end))
        start_word = end_word
    return pieces


def _density(document: StructuredDocument) -> tuple[float, float, float]:
    indexable = [block for block in document.blocks if is_indexable_block(block)]
    total = len(indexable)
    if total == 0:
        return 0.0, 0.0, 0.0
    tables = sum(
        1 for block in indexable if block.kind is StructuredBlockKind.TABLE
    )
    code = sum(1 for block in indexable if block.kind is StructuredBlockKind.CODE)
    tokens = sum(max(1, token_count(block.text)) for block in indexable)
    return tables / total, code / total, tokens / total


__all__ = ["SemanticWindowPlanner", "WindowBudget"]

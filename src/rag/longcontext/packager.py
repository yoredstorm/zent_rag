# =============================================================================
# ContextPackager — empaquetado inteligente del contexto
# =============================================================================
# Orden por prioridad, no por score puro:
#   0 MUST_KEEP (evidencia exacta)
#   1 anchor exacto
#   2 evidencia directa de un requirement
#   3 contexto padre / sección
#   4 evidencia de apoyo
#   5 background
# Antes de presupuestar: dedupe exacto, normalizado y near-duplicate, y
# reconstrucción de secciones partidas (preferir la sección una vez). Cada
# bloque conserva metadata de procedencia para citations y Ver flujo.
# =============================================================================
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from src.core.domain.entities import RetrievalChunk
from src.rag.longcontext.must_keep import (
    is_exact_anchor,
    is_must_keep,
    is_requirement_evidence,
    is_supporting_exact,
    must_keep_level,
)

PRIORITY_RULE = 0
PRIORITY_MUST_KEEP = PRIORITY_RULE  # compat
PRIORITY_REQUIREMENT = 1
PRIORITY_FIELD = 2
PRIORITY_EXACT = PRIORITY_FIELD  # compat
PRIORITY_PARENT = 3
PRIORITY_SUPPORT = 4
PRIORITY_BACKGROUND = 5

_PRIORITY_REASONS = {
    PRIORITY_RULE: "must_keep_rule",
    PRIORITY_REQUIREMENT: "requirement_evidence",
    PRIORITY_FIELD: "exact_field",
    PRIORITY_PARENT: "parent_context",
    PRIORITY_SUPPORT: "supporting_context",
    PRIORITY_BACKGROUND: "background",
}

_CHARS_PER_TOKEN = 4
_DEFAULT_MAX_SECTION_CHARS = 24_000
_NEAR_DUP_THRESHOLD = 0.85
_MIN_OVERLAP_CHARS = 40
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_PARENT_RETRIEVALS = (
    "parent",
    "section",
    "entity_section",
    "expansion_parent",
    "expansion_section",
    "reconstructed",
)


@dataclass(kw_only=True)
class ContextBlock:
    """Bloque del contexto con su porqué y procedencia."""

    chunk: RetrievalChunk
    priority: int
    reason: str
    tokens: int
    unit_key: str = ""
    unit_type: str = "paragraph"
    metadata: dict[str, str] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        meta = self.chunk.metadata or {}
        payload: dict[str, Any] = {
            "priority": self.priority,
            "reason": self.reason,
            "tokens": self.tokens,
            "document_id": str(self.chunk.document_id),
            "chunk_id": str(meta.get("chunk_id") or ""),
            "source_id": str(meta.get("source_id") or ""),
            "page": meta.get("page_start"),
            "section_path": meta.get("section_path"),
            "retrieval": str(meta.get("retrieval") or ""),
            "score": round(float(self.chunk.score or 0.0), 4),
        }
        if self.unit_key:
            payload["semantic_unit"] = self.unit_type
        return payload


@dataclass(kw_only=True)
class PackResult:
    blocks: list[ContextBlock]
    used_tokens: int
    budget_tokens: int
    dropped: list[dict[str, Any]] = field(default_factory=list)
    deduped: int = 0
    reconstructed: int = 0
    overflow_tokens: int = 0

    @property
    def chunks(self) -> list[RetrievalChunk]:
        return [block.chunk for block in self.blocks]

    def stats(self) -> dict[str, Any]:
        by_priority: dict[str, int] = {}
        for block in self.blocks:
            key = str(block.priority)
            by_priority[key] = by_priority.get(key, 0) + 1
        return {
            "blocks": len(self.blocks),
            "used_tokens": self.used_tokens,
            "budget_tokens": self.budget_tokens,
            "deduped": self.deduped,
            "reconstructed": self.reconstructed,
            "overflow_tokens": self.overflow_tokens,
            "dropped": len(self.dropped),
            "by_priority": by_priority,
        }


class ContextPackager:
    """Empaqueta chunks en bloques priorizados y presupuestados."""

    def __init__(self, *, max_section_chars: int = _DEFAULT_MAX_SECTION_CHARS) -> None:
        self._max_section_chars = max(2000, int(max_section_chars))

    def pack(
        self,
        chunks: list[RetrievalChunk],
        *,
        budget_tokens: int,
        hard_budget_tokens: int | None = None,
        preserve_units: bool = True,
        requirements: list[Any] | tuple[Any, ...] = (),
        anchors: list[Any] | tuple[Any, ...] = (),
    ) -> PackResult:
        """Empaqueta con soft budget + headroom para unidades completas.

        `budget_tokens` es el SOFT limit (tier); `hard_budget_tokens` el tope
        duro de esta etapa (siguiente tier o usable_context). Una unidad
        semántica (tabla, nota, procedimiento, sección) que no entra en el soft
        pero sí en el hard se conserva ENTERA: mejor 39K coherentes que 32K con
        la explicación cortada.
        """
        budget = max(1, int(budget_tokens))
        hard = max(budget, int(hard_budget_tokens or budget))
        if not chunks:
            return PackResult(blocks=[], used_tokens=0, budget_tokens=budget)

        requirement_needles = _requirement_needles(requirements)
        anchor_needles = _anchor_needles(anchors)

        deduped, removed = self._dedupe(chunks)
        grouped, reconstructed = self._reconstruct_sections(deduped)

        max_score = max((float(chunk.score or 0.0) for chunk in grouped), default=0.0)
        blocks: list[ContextBlock] = []
        for index, chunk in enumerate(grouped):
            priority, reason = _classify(
                chunk,
                index=index,
                max_score=max_score,
                requirement_needles=requirement_needles,
                anchor_needles=anchor_needles,
            )
            content = chunk.content or ""
            blocks.append(
                ContextBlock(
                    chunk=chunk,
                    priority=priority,
                    reason=reason,
                    tokens=max(1, len(content) // _CHARS_PER_TOKEN),
                    unit_key=_unit_key(chunk),
                    unit_type=_unit_type(chunk),
                    metadata={
                        "document_id": str(chunk.document_id),
                        "source_id": str((chunk.metadata or {}).get("source_id") or ""),
                        "filename": str(
                            (chunk.metadata or {}).get("filename")
                            or (chunk.metadata or {}).get("title")
                            or ""
                        ),
                        "page": str((chunk.metadata or {}).get("page_start") or ""),
                        "section_path": str(
                            (chunk.metadata or {}).get("section_path") or ""
                        ),
                        "chunk_id": str((chunk.metadata or {}).get("chunk_id") or ""),
                        "parent_id": str((chunk.metadata or {}).get("parent_id") or ""),
                        "retrieval_method": str(
                            (chunk.metadata or {}).get("retrieval") or ""
                        ),
                        "rerank_score": str(
                            (chunk.metadata or {}).get("rerank_score") or ""
                        ),
                        "exact_anchor": "true" if is_exact_anchor(chunk) else "",
                        "must_keep": "true" if is_must_keep(chunk) else "",
                        "requirement_evidence": (
                            "true" if is_requirement_evidence(chunk) else ""
                        ),
                    },
                )
            )

        blocks.sort(key=lambda block: (block.priority, -float(block.chunk.score or 0.0)))
        selected_flags = [False] * len(blocks)
        used = 0

        # 1) Protegidos: MUST_KEEP (regla/campo/referencia) y evidencia de
        # requirement nunca se caen, sin importar el nivel.
        for index, block in enumerate(blocks):
            if is_must_keep(block.chunk) or is_requirement_evidence(block.chunk):
                selected_flags[index] = True
                used += block.tokens

        units: dict[str, list[int]] = {}
        for index, block in enumerate(blocks):
            if block.unit_key:
                units.setdefault(block.unit_key, []).append(index)

        handled: set[str] = set()
        # 2) Selección por unidad (unidad entera antes que corte por tier).
        for index, block in enumerate(blocks):
            if selected_flags[index]:
                continue
            key = block.unit_key
            if preserve_units and key:
                if key in handled:
                    continue
                handled.add(key)
                members = [i for i in units[key] if not selected_flags[i]]
                if not members:
                    continue
                unit_cost = sum(blocks[i].tokens for i in members)
                fits_soft = used + unit_cost <= budget
                fits_hard = used + unit_cost <= hard
                meaningful = len(members) > 1 or block.unit_type in (
                    "table",
                    "note",
                    "procedure",
                    "code_block",
                    "section",
                    "definition",
                )
                if fits_soft or (meaningful and fits_hard):
                    for i in members:
                        selected_flags[i] = True
                    used += unit_cost
                    continue
                # No entra ni con headroom: selección individual hasta el hard.
                for i in members:
                    if used + blocks[i].tokens <= hard:
                        selected_flags[i] = True
                        used += blocks[i].tokens
                continue
            if used + block.tokens <= budget or (
                block.unit_type in ("table", "note", "procedure", "code_block", "section", "definition")
                and used + block.tokens <= hard
            ):
                selected_flags[index] = True
                used += block.tokens

        selected = [block for index, block in enumerate(blocks) if selected_flags[index]]
        dropped = [
            {
                "priority": block.priority,
                "reason": block.reason,
                "chunk_id": block.metadata.get("chunk_id", ""),
                "unit": block.unit_type,
                "tokens": block.tokens,
                "dropped": "budget",
            }
            for index, block in enumerate(blocks)
            if not selected_flags[index]
        ]

        overflow = max(0, used - budget)
        return PackResult(
            blocks=selected,
            used_tokens=used,
            budget_tokens=budget,
            dropped=dropped,
            deduped=removed,
            reconstructed=reconstructed,
            overflow_tokens=overflow,
        )

    # ------------------------------------------------------------------
    # Dedupe
    # ------------------------------------------------------------------
    def _dedupe(self, chunks: list[RetrievalChunk]) -> tuple[list[RetrievalChunk], int]:
        kept: list[RetrievalChunk] = []
        kept_tokens: list[set[str]] = []
        exact_hashes: set[str] = set()
        normalized_hashes: set[str] = set()
        removed = 0
        for chunk in chunks:
            content = chunk.content or ""
            exact = _text_hash(content)
            normalized = _normalized_hash(content)
            if exact in exact_hashes or normalized in normalized_hashes:
                removed += 1
                continue
            tokens = _tokens(content)
            if self._find_near_duplicate(chunk, tokens, kept, kept_tokens) is not None:
                removed += 1
                continue
            exact_hashes.add(exact)
            normalized_hashes.add(normalized)
            kept.append(chunk)
            kept_tokens.append(tokens)
        return kept, removed

    @staticmethod
    def _find_near_duplicate(
        chunk: RetrievalChunk,
        tokens: set[str],
        kept: list[RetrievalChunk],
        kept_tokens: list[set[str]],
    ) -> RetrievalChunk | None:
        if len(tokens) < 8:
            return None
        for index, other in enumerate(kept):
            other_tokens = kept_tokens[index]
            if len(other_tokens) < 8:
                continue
            if not _same_scope(chunk, other):
                continue
            inter = len(tokens & other_tokens)
            union = len(tokens | other_tokens)
            if union and inter / union >= _NEAR_DUP_THRESHOLD:
                return other
        return None

    # ------------------------------------------------------------------
    # Reconstrucción de secciones
    # ------------------------------------------------------------------
    def _reconstruct_sections(
        self,
        chunks: list[RetrievalChunk],
    ) -> tuple[list[RetrievalChunk], int]:
        groups: dict[str, list[RetrievalChunk]] = {}
        order: list[str] = []
        for chunk in chunks:
            key = _section_key(chunk)
            if key:
                if key not in groups:
                    order.append(key)
                    groups[key] = []
                groups[key].append(chunk)
            else:
                order.append(f"__solo__{len(order)}")
                groups[order[-1]] = [chunk]

        result: list[RetrievalChunk] = []
        reconstructed = 0
        for key in order:
            members = groups[key]
            if len(members) < 2:
                result.extend(members)
                continue
            total_chars = sum(len(member.content or "") for member in members)
            if total_chars > self._max_section_chars:
                result.extend(members)
                continue
            merged = _merge_members(members)
            if merged is None or len(merged.content or "") < 2:
                result.extend(members)
                continue
            result.append(merged)
            reconstructed += 1
        return result, reconstructed


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _text_hash(text: str) -> str:
    stripped = _WS_RE.sub(" ", text).strip()
    return hashlib.sha1(stripped.encode("utf-8", "ignore")).hexdigest()  # noqa: S324


def _normalized_hash(text: str) -> str:
    normalized = _NON_ALNUM_RE.sub("", text.lower())
    return hashlib.sha1(normalized.encode("utf-8", "ignore")).hexdigest()  # noqa: S324


def _same_scope(a: RetrievalChunk, b: RetrievalChunk) -> bool:
    meta_a, meta_b = a.metadata or {}, b.metadata or {}
    key_a = _section_key(a)
    key_b = _section_key(b)
    if key_a and key_b and key_a == key_b:
        return True
    source_a = str(meta_a.get("source_id") or "")
    source_b = str(meta_b.get("source_id") or "")
    if source_a and source_a == source_b:
        return True
    return False


def _section_key(chunk: RetrievalChunk) -> str:
    metadata = chunk.metadata or {}
    parent = str(metadata.get("parent_id") or "")
    if parent:
        return f"parent:{parent}"
    section = str(metadata.get("section_id") or "")
    if section:
        return f"section:{section}"
    path = metadata.get("section_path")
    source = str(metadata.get("source_id") or "")
    if path and source:
        return f"path:{source}:{path}"
    return ""


#: Tipos de unidad semántica que no se parten arbitrariamente.
SEMANTIC_UNIT_TYPES = (
    "paragraph",
    "table",
    "note",
    "section",
    "procedure",
    "code_block",
    "definition",
)

_CODE_BLOCK_RE = re.compile(r"```")
_NOTE_RE = re.compile(r"^\s*(nota|note|footnote|advertencia|warning)\b", re.IGNORECASE | re.MULTILINE)
_PROCEDURE_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+\S", re.MULTILINE)
_DEFINITION_RE = re.compile(r"^\s*[A-Z][A-Za-z0-9 _-]{1,40}\s*[:=]\s*\S")


def _unit_key(chunk: RetrievalChunk) -> str:
    """Unidad lógica: padre/sección. Sin estructura, cada chunk es su unidad."""
    metadata = chunk.metadata or {}
    retrieval = str(metadata.get("retrieval") or "")
    if "reconstructed" in retrieval or str(metadata.get("v2_parent") or "").lower() == "true":
        key = _section_key(chunk)
        if key:
            return key
    return _section_key(chunk)


def _unit_type(chunk: RetrievalChunk) -> str:
    """Tipo de unidad por metadata y forma; nunca corta listas/tablas/notas."""
    metadata = chunk.metadata or {}
    content = chunk.content or ""
    chunk_type = str(metadata.get("chunk_type") or "").lower()
    retrieval = str(metadata.get("retrieval") or "").lower()
    if (
        "table" in chunk_type
        or "tabular" in chunk_type
        or str(metadata.get("v2_tabular") or "").lower() in ("true", "1")
    ):
        return "table"
    if "reconstructed" in retrieval or (
        "v2_parent" in metadata and str(metadata.get("v2_parent")).lower() == "true"
    ):
        return "section"
    if "note" in chunk_type:
        return "note"
    if "code" in chunk_type or _CODE_BLOCK_RE.search(content):
        return "code_block"
    if _NOTE_RE.search(content):
        return "note"
    if _PROCEDURE_RE.search(content) and len(content) < 4000:
        return "procedure"
    if " | " in content or "\t" in content:
        return "table"
    first_line = content.strip().splitlines()[0] if content.strip() else ""
    if _DEFINITION_RE.match(first_line) and len(first_line) <= 60:
        return "definition"
    return "paragraph"


def _merge_members(members: list[RetrievalChunk]) -> RetrievalChunk | None:
    """Fusiona chunks de una sección con overlap, preservando metadata común."""
    ordered = sorted(
        members,
        key=lambda chunk: (
            _int_or_none((chunk.metadata or {}).get("chunk_index")),
            -float(chunk.score or 0.0),
        ),
    )
    merged = ""
    for member in ordered:
        merged = _merge_pair(merged, member.content or "")
    merged = _dedupe_lines(merged)
    if not merged.strip():
        return None
    best = max(ordered, key=lambda chunk: float(chunk.score or 0.0))
    metadata = {
        **(best.metadata or {}),
        "retrieval": "section_reconstructed",
        "reconstructed": "true",
        "section_chunks": str(len(members)),
    }
    return RetrievalChunk(
        document_id=best.document_id,
        content=merged,
        score=float(best.score or 0.0),
        metadata=metadata,
    )


def _int_or_none(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1_000_000


def _merge_pair(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    limit = min(len(left), len(right), 4000)
    for size in range(limit, _MIN_OVERLAP_CHARS - 1, -1):
        if left[-size:] == right[:size]:
            return left + right[size:]
    return f"{left}\n{right}"


def _dedupe_lines(text: str) -> str:
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        key = line.strip()
        if len(key) >= 30:
            if key in seen:
                continue
            seen.add(key)
        lines.append(line)
    return "\n".join(lines)


def _classify(
    chunk: RetrievalChunk,
    *,
    index: int,
    max_score: float,
    requirement_needles: list[str],
    anchor_needles: list[str],
) -> tuple[int, str]:
    metadata = chunk.metadata or {}
    if is_must_keep(chunk):
        level = must_keep_level(chunk)
        if level == "field":
            return PRIORITY_FIELD, _PRIORITY_REASONS[PRIORITY_FIELD]
        if level in ("reference", "entity"):
            return PRIORITY_REQUIREMENT, "exact_reference"
        return PRIORITY_RULE, (
            "must_keep_rule" if level == "rule" else _PRIORITY_REASONS[PRIORITY_RULE]
        )
    if is_requirement_evidence(chunk):
        return PRIORITY_REQUIREMENT, "requirement_evidence"
    if is_supporting_exact(chunk):
        return PRIORITY_SUPPORT, "supporting_exact"
    if is_exact_anchor(chunk):
        return PRIORITY_FIELD, _PRIORITY_REASONS[PRIORITY_FIELD]
    retrieval = str(metadata.get("retrieval") or "")
    content = (chunk.content or "").lower()
    if requirement_needles and any(needle in content for needle in requirement_needles):
        return PRIORITY_REQUIREMENT, _PRIORITY_REASONS[PRIORITY_REQUIREMENT]
    if retrieval.startswith(_PARENT_RETRIEVALS) or str(
        metadata.get("v2_parent") or ""
    ).lower() == "true":
        return PRIORITY_PARENT, _PRIORITY_REASONS[PRIORITY_PARENT]
    if anchor_needles and any(needle in content for needle in anchor_needles):
        return PRIORITY_REQUIREMENT, _PRIORITY_REASONS[PRIORITY_REQUIREMENT]
    score = float(chunk.score or 0.0)
    if score > 0 and max_score > 0 and score >= max_score * 0.5:
        return PRIORITY_SUPPORT, _PRIORITY_REASONS[PRIORITY_SUPPORT]
    return PRIORITY_BACKGROUND, _PRIORITY_REASONS[PRIORITY_BACKGROUND]


def _requirement_needles(requirements: list[Any] | tuple[Any, ...]) -> list[str]:
    needles: list[str] = []
    for requirement in requirements or ():
        for needle in getattr(requirement, "needles", ()) or ():
            value = str(needle or "").strip().lower()
            if len(value) >= 2 and value not in needles:
                needles.append(value)
    return needles[:24]


def _anchor_needles(anchors: list[Any] | tuple[Any, ...]) -> list[str]:
    needles: list[str] = []
    for anchor in anchors or ():
        value = str(getattr(anchor, "value", "") or "").strip().lower()
        if len(value) >= 2 and value not in needles:
            needles.append(value)
    return needles[:16]


__all__ = [
    "ContextBlock",
    "ContextPackager",
    "PackResult",
    "PRIORITY_BACKGROUND",
    "PRIORITY_EXACT",
    "PRIORITY_MUST_KEEP",
    "PRIORITY_PARENT",
    "PRIORITY_REQUIREMENT",
    "PRIORITY_SUPPORT",
]

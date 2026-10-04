# =============================================================================
# SemanticStitcher — coser significado entre ventanas (§14-15)
# =============================================================================
# Los chunks no "hablan". La cadena es:
#
#   PHYSICAL UNIT -> SEMANTIC UNIT -> SEMANTIC RELATIONSHIP -> SEMANTIC UNIT
#                 -> PHYSICAL EVIDENCE
#
# El stitcher consume los resultados de TODAS las ventanas y produce:
#   - unidades semánticas merged (misma clave en N ventanas = una unidad);
#   - relaciones tipadas (DEFINES/USES/HAS_EXCEPTION/REFERENCES/ALIAS_OF/
#     CONTRADICTS/SUPERSEDES/SAME_AS/HAS_ATTRIBUTE/HAS_CONDITION/PART_OF/...);
#   - detección de duplicados, contradicciones y supersession temporal;
#   - cierre de SemanticThreads que quedaron abiertos usando las unidades.
#
# Determinista. Toda relación tiene evidencia (block_ids) y ventanas.
# Nada se auto-promueve a canónico: es señal derivada.
# =============================================================================
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from hashlib import sha256
from uuid import UUID, uuid5

from src.knowledge.compiler.model import normalize_term

from .contracts import SemanticWindowResult
from .threads import SemanticThread, ThreadStatus, ThreadType

STITCH_VERSION = "semantic-stitch-1"

STITCH_NS = UUID("e5b8c2d4-1a7f-4d3b-9e6c-7a4f8b2d1c53")

#: Relaciones del vocabulario de la misión (§21) que la Fase 5 produce.
STITCH_RELATION_TYPES: tuple[str, ...] = (
    "DEFINES",
    "USES",
    "HAS_ATTRIBUTE",
    "HAS_CONDITION",
    "HAS_EXCEPTION",
    "REFERENCES",
    "ALIAS_OF",
    "SAME_AS",
    "CONTRADICTS",
    "SUPERSEDES",
    "PART_OF",
    "DERIVED_FROM",
    "RELATED_TO",
)

#: Unidades de conocimiento (las continuaciones/topics no entran al grafo).
_UNIT_KINDS: tuple[str, ...] = (
    "definition",
    "symbol",
    "entity",
    "concept",
    "rule",
    "condition",
    "exception",
    "procedure",
    "claim",
    "temporal",
    "reference",
    "unresolved_reference",
    "table",
    "alias",
    "conflict",
    "note",
)

_TEXTUAL_KINDS = frozenset(
    {"rule", "condition", "exception", "procedure", "claim", "definition", "note"}
)
_REFERENCE_KINDS = frozenset({"reference", "unresolved_reference"})


@dataclass(frozen=True, kw_only=True)
class StitchedUnit:
    """Unidad semántica merged de todo el documento."""

    id: UUID
    unit_key: str
    unit_kind: str
    label: str
    text: str = ""
    confidence: float = 0.6
    source_windows: tuple[int, ...] = ()
    block_ids: tuple[str, ...] = ()
    merged_from: tuple[str, ...] = ()
    attributes: dict = field(default_factory=dict)
    version: str = STITCH_VERSION

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "unit_key": self.unit_key,
            "unit_kind": self.unit_kind,
            "label": self.label[:300],
            "text": self.text[:600],
            "confidence": round(float(self.confidence), 4),
            "source_windows": list(self.source_windows),
            "block_ids": list(self.block_ids),
            "merged_from": list(self.merged_from),
            "attributes": dict(self.attributes),
            "derived": True,
            "canonical": False,
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class StitchRelation:
    """Relación tipada entre unidades semánticas, con evidencia física."""

    id: UUID
    relation_key: str
    relation_type: str
    subject_key: str
    subject_kind: str
    subject_label: str
    object_key: str
    object_kind: str
    object_label: str
    confidence: float = 0.7
    method: str = "deterministic"
    evidence: tuple[str, ...] = ()
    windows: tuple[int, ...] = ()
    attributes: dict = field(default_factory=dict)
    version: str = STITCH_VERSION

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "relation_key": self.relation_key,
            "relation_type": self.relation_type,
            "subject_key": self.subject_key,
            "subject_kind": self.subject_kind,
            "subject_label": self.subject_label[:200],
            "object_key": self.object_key,
            "object_kind": self.object_kind,
            "object_label": self.object_label[:200],
            "confidence": round(float(self.confidence), 4),
            "method": self.method,
            "evidence": list(self.evidence),
            "windows": list(self.windows),
            "attributes": dict(self.attributes),
            "derived": True,
            "canonical": False,
            "version": self.version,
        }


@dataclass(frozen=True, kw_only=True)
class StitchOutcome:
    units: tuple[StitchedUnit, ...] = ()
    relations: tuple[StitchRelation, ...] = ()
    threads_updated: tuple[SemanticThread, ...] = ()
    threads_closed: int = 0
    threads_ambiguous: int = 0
    duplicates: int = 0
    contradictions: int = 0
    supersessions: int = 0
    version: str = STITCH_VERSION

    def to_dict(self) -> dict:
        return {
            "units": len(self.units),
            "relations": len(self.relations),
            "threads_closed": self.threads_closed,
            "threads_ambiguous": self.threads_ambiguous,
            "duplicates": self.duplicates,
            "contradictions": self.contradictions,
            "supersessions": self.supersessions,
            "version": self.version,
            "relation_counts": _count_by(self.relations, "relation_type"),
            "unit_counts": _count_by(self.units, "unit_kind"),
        }


class SemanticStitcher:
    """Cose las ventanas de un documento en unidades + relaciones."""

    version = STITCH_VERSION

    def __init__(
        self,
        *,
        max_units: int = 20000,
        max_relations: int = 50000,
        max_uses_per_unit: int = 16,
    ) -> None:
        self._max_units = max(1, int(max_units))
        self._max_relations = max(1, int(max_relations))
        self._max_uses = max(1, int(max_uses_per_unit))

    def stitch(
        self,
        *,
        document,
        results: list[SemanticWindowResult],
        threads: list[SemanticThread],
    ) -> StitchOutcome:
        document_id = getattr(document, "id", None)
        units = self._build_units(results)
        units = self._stitch_continuations(results, units)
        relations: dict[str, StitchRelation] = {}
        duplicates = contradictions = supersessions = 0

        self._stitch_defines(units, relations, document_id)
        self._stitch_uses(units, relations, document_id)
        self._stitch_attributes(units, relations, document_id)
        self._stitch_rules(units, relations, document_id)
        self._stitch_references(units, relations, document_id)
        self._stitch_aliases(units, relations, document_id)
        duplicates = self._stitch_duplicates(units, relations, document_id)
        contradictions, supersessions = self._stitch_claims(
            units, relations, document_id
        )
        self._stitch_part_of(units, relations, document_id)

        thread_updates, closed, ambiguous = self._close_threads(
            threads, units, document_id=document_id
        )
        return StitchOutcome(
            units=tuple(units.values())[: self._max_units],
            relations=tuple(relations.values())[: self._max_relations],
            threads_updated=tuple(thread_updates),
            threads_closed=closed,
            threads_ambiguous=ambiguous,
            duplicates=duplicates,
            contradictions=contradictions,
            supersessions=supersessions,
        )

    # ------------------------------------------------------------------
    # Unidades
    # ------------------------------------------------------------------
    def _build_units(
        self, results: list[SemanticWindowResult]
    ) -> dict[str, StitchedUnit]:
        merged: dict[str, StitchedUnit] = {}
        for result in sorted(results, key=lambda item: item.window_index):
            for item in result.items:
                if item.kind not in _UNIT_KINDS:
                    continue
                unit_key = _unit_key(item)
                if not unit_key:
                    continue
                existing = merged.get(unit_key)
                windows = (int(result.window_index),)
                if existing is None:
                    merged[unit_key] = StitchedUnit(
                        id=uuid5(
                            STITCH_NS,
                            f"{result.document_id}|{unit_key}",
                        ),
                        unit_key=unit_key,
                        unit_kind=item.kind,
                        label=item.label,
                        text=item.text,
                        confidence=float(item.confidence),
                        source_windows=windows,
                        block_ids=item.block_ids,
                        merged_from=(item.key,),
                        attributes=dict(item.attributes),
                    )
                    continue
                best_text = (
                    item.text if len(item.text) > len(existing.text) else existing.text
                )
                merged[unit_key] = StitchedUnit(
                    id=existing.id,
                    unit_key=existing.unit_key,
                    unit_kind=existing.unit_kind,
                    label=existing.label or item.label,
                    text=best_text,
                    confidence=max(existing.confidence, float(item.confidence)),
                    source_windows=tuple(
                        sorted({*existing.source_windows, *windows})
                    ),
                    block_ids=tuple(
                        dict.fromkeys((*existing.block_ids, *item.block_ids))
                    ),
                    merged_from=tuple(
                        dict.fromkeys((*existing.merged_from, item.key))
                    ),
                    attributes={**existing.attributes, **item.attributes},
                )
        return dict(sorted(merged.items()))

    # ------------------------------------------------------------------
    # Fase 7: continuation stitching
    # ------------------------------------------------------------------
    def _stitch_continuations(
        self, results: list[SemanticWindowResult], units: dict[str, StitchedUnit]
    ) -> dict[str, StitchedUnit]:
        """Cose una continuación abierta con el primer item textual siguiente.

        La unidad resultante conserva el texto continuado y los block_ids de
        AMBAS ventanas; los resultados de ventana (evidencia) quedan intactos.
        """
        by_window = {result.window_index: result for result in results}
        for result in sorted(results, key=lambda item: item.window_index):
            next_result = by_window.get(result.window_index + 1)
            if next_result is None or not result.continuation_candidates:
                continue
            continuation = result.continuation_candidates[-1]
            target = next(
                (
                    item
                    for item in next_result.items
                    if item.kind
                    in {
                        "definition",
                        "claim",
                        "rule",
                        "note",
                        "procedure",
                        "condition",
                        "exception",
                    }
                ),
                None,
            )
            if target is None:
                continue
            unit_key = _unit_key(target)
            existing = units.get(unit_key)
            if existing is None:
                continue
            merged_text = " ".join(
                part
                for part in (continuation.text.strip(), existing.text.strip())
                if part
            ).strip()
            if not merged_text or merged_text == existing.text:
                continue
            units[unit_key] = dataclasses.replace(
                existing,
                text=merged_text,
                block_ids=tuple(
                    dict.fromkeys((*continuation.block_ids, *existing.block_ids))
                ),
                source_windows=tuple(
                    sorted(
                        {
                            *existing.source_windows,
                            int(result.window_index),
                        }
                    )
                ),
                merged_from=tuple(
                    dict.fromkeys((*existing.merged_from, continuation.key))
                ),
                attributes={
                    **existing.attributes,
                    "continuation_stitched": True,
                    "continuation_key": continuation.key,
                },
            )
        return units

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------
    def _add(
        self,
        relations: dict[str, StitchRelation],
        *,
        document_id,
        relation_type: str,
        subject: StitchedUnit,
        object_unit: StitchedUnit,
        confidence: float,
        evidence: tuple[str, ...] = (),
        windows: tuple[int, ...] = (),
        attributes: dict | None = None,
    ) -> None:
        key = f"{relation_type}:{subject.unit_key}->{object_unit.unit_key}"
        if key in relations:
            return
        relations[key] = StitchRelation(
            id=uuid5(STITCH_NS, f"{document_id}|{key}"),
            relation_key=key,
            relation_type=relation_type,
            subject_key=subject.unit_key,
            subject_kind=subject.unit_kind,
            subject_label=subject.label,
            object_key=object_unit.unit_key,
            object_kind=object_unit.unit_kind,
            object_label=object_unit.label,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            evidence=tuple(
                dict.fromkeys((*evidence, *subject.block_ids, *object_unit.block_ids))
            )[:32],
            windows=tuple(
                sorted({*windows, *subject.source_windows, *object_unit.source_windows})
            ),
            attributes=dict(attributes or {}),
        )

    def _stitch_defines(self, units, relations, document_id) -> None:
        definitions = [unit for unit in units.values() if unit.unit_kind == "definition"]
        targets = [
            unit
            for unit in units.values()
            if unit.unit_kind in {"symbol", "entity", "concept"}
        ]
        for definition in definitions:
            label = _norm(definition.label)
            for target in targets:
                target_label = _norm(target.label)
                if label and (
                    target_label == label
                    or (len(label) >= 3 and label in _norm(target.text))
                    or (target.unit_kind == "symbol" and target.label in definition.text)
                ):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="DEFINES",
                        subject=definition,
                        object_unit=target,
                        confidence=0.85,
                        attributes={"definition": definition.text[:200]},
                    )
    def _stitch_uses(self, units, relations, document_id) -> None:
        textual = [unit for unit in units.values() if unit.unit_kind in _TEXTUAL_KINDS]
        targets = [
            unit
            for unit in units.values()
            if unit.unit_kind in {"symbol", "entity", "concept"}
        ]
        for source in textual:
            used = 0
            for target in targets:
                if used >= self._max_uses:
                    break
                if _mentions(source.text or source.label, target):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="USES",
                        subject=source,
                        object_unit=target,
                        confidence=0.75,
                    )
                    used += 1

    def _stitch_attributes(self, units, relations, document_id) -> None:
        symbols = {
            unit.label: unit for unit in units.values() if unit.unit_kind == "symbol"
        }
        for unit in units.values():
            if unit.unit_kind != "entity":
                continue
            pattern = str(
                unit.attributes.get("literal_pattern")
                or unit.attributes.get("relation_target")
                or ""
            ).strip()
            symbol = symbols.get(pattern)
            if symbol is not None:
                self._add(
                    relations,
                    document_id=document_id,
                    relation_type="HAS_ATTRIBUTE",
                    subject=unit,
                    object_unit=symbol,
                    confidence=0.9,
                    attributes={"pattern": pattern},
                )

    def _stitch_rules(self, units, relations, document_id) -> None:
        rules = [unit for unit in units.values() if unit.unit_kind == "rule"]
        conditions = [unit for unit in units.values() if unit.unit_kind == "condition"]
        exceptions = [unit for unit in units.values() if unit.unit_kind == "exception"]
        for rule in rules:
            for condition in conditions:
                if _shares_window(rule, condition) or _mentions(
                    rule.text, condition
                ):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="HAS_CONDITION",
                        subject=rule,
                        object_unit=condition,
                        confidence=0.7,
                    )
            for exception in exceptions:
                symbol = str(
                    exception.attributes.get("target")
                    or _first_symbol(exception.text)
                    or ""
                )
                if (symbol and symbol in f"{rule.label} {rule.text}") or _shares_window(
                    rule, exception
                ):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="HAS_EXCEPTION",
                        subject=rule,
                        object_unit=exception,
                        confidence=0.7,
                    )

    def _stitch_references(self, units, relations, document_id) -> None:
        references = [
            unit for unit in units.values() if unit.unit_kind in _REFERENCE_KINDS
        ]
        targets = [
            unit
            for unit in units.values()
            if unit.unit_kind
            in {"definition", "entity", "concept", "symbol", "rule", "topic", "table"}
        ]
        for reference in references:
            label = _norm(reference.label)
            if not label:
                continue
            for target in targets:
                target_label = (
                    target.label if target.unit_kind == "symbol" else _norm(target.label)
                )
                if target_label == label or (
                    len(label) >= 2 and label in target_label.split()
                ):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="REFERENCES",
                        subject=reference,
                        object_unit=target,
                        confidence=0.8,
                        attributes={"reference_text": reference.text[:200]},
                    )
                    break

    def _stitch_aliases(self, units, relations, document_id) -> None:
        aliases = [unit for unit in units.values() if unit.unit_kind == "alias"]
        targets = [
            unit
            for unit in units.values()
            if unit.unit_kind in {"concept", "entity", "definition"}
        ]
        for alias in aliases:
            canonical = _norm(str(alias.attributes.get("canonical") or ""))
            label = _norm(alias.label)
            for target in targets:
                target_label = _norm(target.label)
                if (canonical and target_label == canonical) or target_label == label:
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="ALIAS_OF",
                        subject=alias,
                        object_unit=target,
                        confidence=0.85,
                        attributes={"canonical": target.label},
                    )
                    break

    def _stitch_duplicates(self, units, relations, document_id) -> int:
        by_text: dict[str, list[StitchedUnit]] = {}
        for unit in units.values():
            tokens = _tokens(unit.text or unit.label)
            if len(tokens) < 4:
                continue
            key = " ".join(sorted(tokens))
            by_text.setdefault(key, []).append(unit)
        duplicates = 0
        for group in by_text.values():
            if len(group) < 2:
                continue
            ordered = sorted(group, key=lambda item: item.unit_key)
            for index in range(1, len(ordered)):
                duplicates += 1
                self._add(
                    relations,
                    document_id=document_id,
                    relation_type="SAME_AS",
                    subject=ordered[index],
                    object_unit=ordered[0],
                    confidence=0.85,
                    attributes={"reason": "identical_normalized_text"},
                )
        return duplicates

    def _stitch_claims(self, units, relations, document_id) -> tuple[int, int]:
        claims = [unit for unit in units.values() if unit.unit_kind == "claim"]
        groups: dict[tuple[str, str], list[StitchedUnit]] = {}
        for claim in claims:
            subject = _norm(str(claim.attributes.get("subject") or ""))
            predicate = _norm(str(claim.attributes.get("predicate") or ""))
            if subject and predicate:
                groups.setdefault((subject, predicate), []).append(claim)
        contradictions = supersessions = 0
        temporal_windows = {
            window
            for unit in units.values()
            if unit.unit_kind == "temporal"
            for window in unit.source_windows
        }
        for group in groups.values():
            values = {
                _norm(str(unit.attributes.get("object_value") or ""))
                for unit in group
            }
            values.discard("")
            if len(values) < 2:
                continue
            ordered = sorted(group, key=lambda item: min(item.source_windows or (0,)))
            for index in range(1, len(ordered)):
                later, earlier = ordered[index], ordered[index - 1]
                contradictions += 1
                self._add(
                    relations,
                    document_id=document_id,
                    relation_type="CONTRADICTS",
                    subject=later,
                    object_unit=earlier,
                    confidence=0.7,
                    attributes={
                        "value_later": later.attributes.get("object_value"),
                        "value_earlier": earlier.attributes.get("object_value"),
                        "requires_review": True,
                    },
                )
                if temporal_windows.intersection(later.source_windows):
                    supersessions += 1
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="SUPERSEDES",
                        subject=later,
                        object_unit=earlier,
                        confidence=0.55,
                        attributes={
                            "reason": "temporal_marker_in_later_window",
                            "requires_review": True,
                        },
                    )
        return contradictions, supersessions

    def _stitch_part_of(self, units, relations, document_id) -> None:
        topics = [unit for unit in units.values() if unit.unit_kind == "topic"]
        for unit in units.values():
            if unit.unit_kind not in {"table", "definition", "rule", "procedure"}:
                continue
            for topic in topics:
                if _shares_window(unit, topic):
                    self._add(
                        relations,
                        document_id=document_id,
                        relation_type="PART_OF",
                        subject=unit,
                        object_unit=topic,
                        confidence=0.7,
                    )
                    break

    # ------------------------------------------------------------------
    # Cierre de threads
    # ------------------------------------------------------------------
    def _close_threads(
        self,
        threads: list[SemanticThread],
        units: dict[str, StitchedUnit],
        *,
        document_id,
    ) -> tuple[list[SemanticThread], int, int]:
        from dataclasses import replace

        updated: list[SemanticThread] = []
        closed = ambiguous = 0
        last_window = max(
            (max(unit.source_windows) for unit in units.values() if unit.source_windows),
            default=-1,
        )
        for thread in threads:
            if not thread.is_open or thread.thread_type == ThreadType.CONTINUATION.value:
                continue
            candidates = unit_candidates_for_thread(thread, units)
            if not candidates:
                continue
            best = max(candidates, key=lambda item: item.confidence)
            if len(candidates) > 1 and best.confidence < 0.85:
                status = ThreadStatus.AMBIGUOUS.value
                resolved_by = None
                ambiguous += 1
            else:
                status = ThreadStatus.RESOLVED.value
                resolved_by = str(best.id)
                closed += 1
            updated.append(
                replace(
                    thread,
                    status=status,
                    resolved_at_window=(
                        int(thread.resolved_at_window)
                        if thread.resolved_at_window is not None
                        else int(max(last_window, thread.opened_at_window))
                    ),
                    resolved_by_unit=resolved_by,
                    confidence=round(float(best.confidence), 4),
                    candidates=tuple(
                        {
                            "kind": item.unit_kind,
                            "label": item.label[:200],
                            "unit_id": str(item.id),
                            "confidence": round(float(item.confidence), 4),
                        }
                        for item in candidates[:8]
                    ),
                    history=(
                        *thread.history,
                        {
                            "window": int(max(last_window, thread.opened_at_window)),
                            "status": status,
                            "reason": "stitcher_closure",
                        },
                    )[-20:],
                )
            )
        return updated, closed, ambiguous


def stitch_fingerprint(outcome: StitchOutcome) -> str:
    """Fingerprint de la etapa de stitch (unidades + relaciones)."""
    import json

    material = {
        "version": outcome.version,
        "units": [unit.unit_key for unit in outcome.units],
        "relations": [relation.relation_key for relation in outcome.relations],
    }
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode("utf-8")).hexdigest()


def unit_candidates_for_thread(
    thread: SemanticThread, units: dict[str, StitchedUnit]
) -> list[StitchedUnit]:
    """Unidades candidatas a cerrar un thread (determinista, por tipo)."""
    label = _norm(thread.target_hint)
    if not label:
        return []
    if thread.thread_type == ThreadType.SYMBOL.value:
        symbol = thread.target_hint
        return [
            unit
            for unit in units.values()
            if (
                unit.unit_kind == "symbol"
                and unit.label == symbol
                and (unit.text or unit.attributes.get("field_name"))
            )
            or (
                unit.unit_kind == "definition"
                and (symbol in unit.text or symbol in unit.label)
            )
            or (
                unit.unit_kind == "entity"
                and str(unit.attributes.get("literal_pattern") or "") == symbol
            )
        ]
    if thread.thread_type == ThreadType.EXCEPTION.value:
        symbol = thread.target_hint
        return [
            unit
            for unit in units.values()
            if unit.unit_kind == "rule" and symbol in f"{unit.label} {unit.text}"
        ]
    candidates = []
    for unit in units.values():
        if unit.unit_kind not in {
            "definition",
            "entity",
            "concept",
            "symbol",
            "rule",
            "topic",
            "table",
        }:
            continue
        unit_label = unit.label if unit.unit_kind == "symbol" else _norm(unit.label)
        if unit_label == label or (len(label) >= 2 and label in unit_label.split()):
            candidates.append(unit)
    return candidates


def _unit_key(item) -> str:
    label = str(item.label or "").strip()
    if item.kind == "symbol":
        return f"symbol:{label}" if label else ""
    if item.kind == "claim":
        subject = normalize_term(str(item.attributes.get("subject") or label))
        predicate = normalize_term(str(item.attributes.get("predicate") or ""))
        object_value = normalize_term(str(item.attributes.get("object_value") or ""))
        if subject and predicate:
            return f"claim:{subject}:{predicate}:{object_value}"
    key = normalize_term(str(item.attributes.get("subject") or label))
    if not key:
        return ""
    return f"{item.kind}:{key}"


def _norm(text: str) -> str:
    return normalize_term(text)


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9_&%#?*\-]{3,}", (text or "").casefold())
        if token
    }


def _mentions(text: str, unit: StitchedUnit) -> bool:
    if not text:
        return False
    if unit.unit_kind == "symbol":
        return unit.label in text
    label = _norm(unit.label)
    if len(label) < 3:
        return False
    return label in _norm(text)


def _shares_window(left: StitchedUnit, right: StitchedUnit) -> bool:
    return bool(set(left.source_windows).intersection(right.source_windows))


def _first_symbol(text: str) -> str | None:
    match = re.search(r"\S*[&%#?*\[\]]\S*", text or "")
    return match.group(0) if match else None


def _count_by(items, attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = str(getattr(item, attribute))
        counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = [
    "STITCH_NS",
    "STITCH_RELATION_TYPES",
    "STITCH_VERSION",
    "SemanticStitcher",
    "StitchOutcome",
    "StitchRelation",
    "StitchedUnit",
    "stitch_fingerprint",
    "unit_candidates_for_thread",
]

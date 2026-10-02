# =============================================================================
# Evidence Assembly — paquete coherente de evidencia (S6, C3).
# =============================================================================
# Compone retrieval + conocimiento canónico en unidades deduplicadas,
# rankeadas y conectadas, con provenance, prioridad de vigencia, conflictos
# retenidos y presupuesto. Sin I/O y sin LLM: determinista.
# =============================================================================
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Sequence

from src.rag.adaptive.passages import sanitize_for_evidence

if TYPE_CHECKING:
    from src.core.domain.adaptive import EvidenceItem
    from src.runtime.entity_resolution import EntityResolution
    from src.runtime.representation_runners import RunnerResult

DEFAULT_ASSEMBLY_BUDGET_CHARS = 12_000
MAX_UNIT_CHARS = 1_200
MAX_UNITS = 40

_KIND_ORDER = {"rule": 0, "fact": 1, "relation": 2, "table": 3, "excerpt": 4}
_RUNNER_KINDS = {"graph": "relation", "temporal": "fact", "structured": "table"}


@dataclass(frozen=True)
class EvidenceUnit:
    unit_id: str
    kind: str
    text: str
    refs: dict = field(default_factory=dict)
    score: float | None = None
    match: str = ""
    evidence_ids: tuple[str, ...] = ()
    canonical_ids: tuple[str, ...] = ()
    validity: str | None = None
    critical: bool = False
    conflict: bool = False
    connected: bool = False

    def to_public_dict(self) -> dict:
        payload = {
            "unit_id": self.unit_id,
            "kind": self.kind,
            "text": self.text,
            "refs": dict(self.refs),
            "match": self.match,
            "critical": self.critical,
            "conflict": self.conflict,
            "connected": self.connected,
        }
        if self.score is not None:
            payload["score"] = round(float(self.score), 4)
        if self.evidence_ids:
            payload["evidence_ids"] = list(self.evidence_ids)
        if self.canonical_ids:
            payload["canonical_ids"] = list(self.canonical_ids)
        if self.validity:
            payload["validity"] = self.validity
        return payload


@dataclass(frozen=True)
class EvidenceConflict:
    key: str
    unit_ids: tuple[str, ...]
    values: tuple[str, ...]

    def to_public_dict(self) -> dict:
        return {
            "key": self.key,
            "unit_ids": list(self.unit_ids),
            "values": list(self.values),
        }


@dataclass(frozen=True)
class EvidencePackage:
    units: tuple[EvidenceUnit, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    dropped: tuple[str, ...] = ()
    chars: int = 0
    budget_chars: int = DEFAULT_ASSEMBLY_BUDGET_CHARS
    counts: dict = field(default_factory=dict)

    def to_public_dict(self, *, max_units: int = 12) -> dict:
        return {
            "count": len(self.units),
            "chars": self.chars,
            "budget_chars": self.budget_chars,
            "counts": dict(self.counts),
            "conflicts": [
                conflict.to_public_dict() for conflict in self.conflicts
            ],
            "dropped_count": len(self.dropped),
            "units": [
                unit.to_public_dict() for unit in self.units[: max(0, max_units)]
            ],
        }


def _clip(text: str, limit: int = MAX_UNIT_CHARS) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _excerpt_key(item: "EvidenceItem") -> str:
    doc = str(item.document_id or item.source_id or "")
    chunk = str(item.chunk_id or "")
    if doc or chunk:
        return f"{doc}|{chunk}"
    digest = hashlib.sha256(
        (item.content or "").encode("utf-8", "ignore")
    ).hexdigest()[:16]
    return f"excerpt|{digest}"


def _is_critical_excerpt(item: "EvidenceItem") -> bool:
    method = str(item.retrieval_method or "")
    return bool(item.entity_pin) or method.startswith(("exact", "entity"))


def _units_from_items(items: Sequence["EvidenceItem"]) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    seen: set[str] = set()
    for item in items or ():
        raw_content = str(item.content or "")
        safe_content, _redacted = sanitize_for_evidence(raw_content)
        content = _clip(safe_content)
        if not content:
            continue
        key = _excerpt_key(item)
        if key in seen:
            continue
        seen.add(key)
        units.append(
            EvidenceUnit(
                unit_id="",
                kind="excerpt",
                text=content,
                refs={
                    "evidence_id": item.evidence_id,
                    "document_id": item.document_id,
                    "chunk_id": item.chunk_id,
                    "title": item.title,
                    "page": item.page,
                    "section_path": list(item.section_path),
                },
                score=float(item.score or 0.0),
                match=str(item.retrieval_method or "semantic"),
                evidence_ids=(item.evidence_id,) if item.evidence_id else (),
                critical=_is_critical_excerpt(item),
            )
        )
    return units


def _units_from_runners(
    results: Sequence["RunnerResult"],
) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    for result in results or ():
        representation = str(getattr(result, "representation", "") or "")
        kind = _RUNNER_KINDS.get(representation)
        if kind is None:
            continue
        for item in getattr(result, "items", ()) or ():
            refs = dict(getattr(item, "refs", None) or {})
            title = str(getattr(item, "title", "") or "").strip()
            text = _clip(title or str(getattr(item, "summary", "") or ""))
            if not text:
                continue
            canonical = str(refs.get("canonical_id") or "")
            units.append(
                EvidenceUnit(
                    unit_id="",
                    kind=kind,
                    text=text,
                    refs=refs,
                    score=getattr(item, "score", None),
                    match=representation,
                    canonical_ids=(canonical,) if canonical else (),
                    validity=str(refs.get("validity") or "") or None,
                )
            )
    return units


def _fact_conflict_key(unit: EvidenceUnit) -> str | None:
    if unit.kind != "fact":
        return None
    canonical = unit.canonical_ids[0] if unit.canonical_ids else ""
    subject = str(unit.refs.get("subject_label") or "").lower()
    predicate = str(unit.refs.get("predicate") or "").lower()
    if not (canonical and predicate):
        return None
    return f"{canonical}|{subject}|{predicate}"


def _conflict_values(units: Sequence[EvidenceUnit]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for unit in units:
        key = _fact_conflict_key(unit)
        if key is None:
            continue
        value = str(unit.refs.get("object_value") or "").strip()
        if value:
            groups.setdefault(key, set()).add(value)
    return {key: values for key, values in groups.items() if len(values) > 1}


def _validity_rank(unit: EvidenceUnit) -> int:
    if unit.validity == "current":
        return 0
    if not unit.validity:
        return 1
    return 2


def _ordered(units: Sequence[EvidenceUnit]) -> list[EvidenceUnit]:
    return sorted(
        units,
        key=lambda unit: (
            _KIND_ORDER.get(unit.kind, 9),
            _validity_rank(unit),
            -float(unit.score or 0.0),
            unit.text.lower(),
        ),
    )


def _apply_budget(
    units: Sequence[EvidenceUnit], budget: int
) -> tuple[list[EvidenceUnit], list[str], int]:
    selected: list[EvidenceUnit] = []
    dropped: list[str] = []
    used = 0
    for unit in units:
        if len(selected) >= MAX_UNITS:
            dropped.append(unit.text[:80])
            continue
        cost = len(unit.text)
        if used + cost > budget:
            dropped.append(unit.text[:80])
            continue
        selected.append(unit)
        used += cost
    return selected, dropped, used


def assemble_evidence(
    *,
    items: Sequence["EvidenceItem"] = (),
    runner_results: Sequence["RunnerResult"] = (),
    entities: "EntityResolution | None" = None,
    budget_chars: int = DEFAULT_ASSEMBLY_BUDGET_CHARS,
) -> EvidencePackage:
    """Paquete coherente: dedupe, prioridad, conflictos retenidos y budget."""
    base = _units_from_items(items) + _units_from_runners(runner_results)
    resolved = {
        mention.matches[0].canonical_id
        for mention in (entities.mentions if entities is not None else ())
        if mention.status == "resolved" and mention.matches
    }
    selected, dropped, used = _apply_budget(
        _ordered(base), max(0, int(budget_chars))
    )
    selected_conflict_values = _conflict_values(selected)
    units: list[EvidenceUnit] = []
    for index, unit in enumerate(selected, start=1):
        key = _fact_conflict_key(unit)
        units.append(
            replace(
                unit,
                unit_id=f"U{index}",
                conflict=bool(key and key in selected_conflict_values),
                connected=bool(set(unit.canonical_ids) & resolved),
            )
        )
    conflicts: list[EvidenceConflict] = []
    for key, values in sorted(selected_conflict_values.items()):
        unit_ids = tuple(
            unit.unit_id for unit in units if _fact_conflict_key(unit) == key
        )
        if len(unit_ids) >= 2:
            conflicts.append(
                EvidenceConflict(
                    key=key, unit_ids=unit_ids, values=tuple(sorted(values))
                )
            )
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.kind] = counts.get(unit.kind, 0) + 1
    counts["critical_excerpts"] = sum(
        1 for unit in units if unit.kind == "excerpt" and unit.critical
    )
    return EvidencePackage(
        units=tuple(units),
        conflicts=tuple(conflicts),
        dropped=tuple(dropped),
        chars=used,
        budget_chars=max(0, int(budget_chars)),
        counts=counts,
    )

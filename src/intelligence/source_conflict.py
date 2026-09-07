# =============================================================================
# Advanced Source Conflict Analyzer (Phase 28C)
# =============================================================================
# Más allá de diffs numéricos: documents vs SQL vs metrics vs definitions.
# Resuelve con authority + effective dates; si no, SOURCE_CONFLICT.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from src.core.domain.intelligence import EvidenceObject, EvidenceType
from src.intelligence.answerability import detect_source_conflicts


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


AUTHORITY_RANK = {
    "authoritative": 3,
    "approved": 2,
    "informational": 1,
    "external": 0,
}


@dataclass
class SourceConflictReport:
    has_conflict: bool
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    resolved: bool = False
    resolved_by: str | None = None
    status: str | None = None  # SOURCE_CONFLICT or None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "conflicts": list(self.conflicts),
            "resolved": self.resolved,
            "resolved_by": self.resolved_by,
            "status": self.status,
            "notes": list(self.notes),
        }


class SourceConflictAnalyzer:
    """Detecta conflictos multi-tipo y aplica authority / effective dating."""

    def analyze(
        self,
        evidences: list[EvidenceObject | dict[str, Any]],
        authority: dict[str, Any] | list[dict[str, Any]] | None = None,
        effective_dates: dict[str, Any] | None = None,
        *,
        as_of: date | datetime | str | None = None,
        tolerance_pct: float = 5.0,
    ) -> SourceConflictReport:
        normalized = [self._normalize(e) for e in evidences]
        conflicts: list[dict[str, Any]] = []

        # 1) Numeric conflicts (reuse gate helper via EvidenceObject when possible)
        objs = [e for e in evidences if isinstance(e, EvidenceObject)]
        if objs:
            for c in detect_source_conflicts(objs, tolerance_pct=tolerance_pct):
                c["conflict_kind"] = "numeric"
                conflicts.append(c)

        # 2) Cross-type semantic conflicts (documents vs SQL vs metrics vs definitions)
        by_claim: dict[str, list[dict[str, Any]]] = {}
        for row in normalized:
            claim = row.get("claim_key") or row.get("metric") or "__generic__"
            by_claim.setdefault(str(claim), []).append(row)

        for claim, group in by_claim.items():
            if len(group) < 2:
                continue
            types = {g.get("evidence_type") for g in group}
            values = {
                self._value_fingerprint(g)
                for g in group
                if self._value_fingerprint(g) is not None
            }
            if len(values) >= 2 and (
                len(types) >= 2
                or any(
                    t
                    in {
                        EvidenceType.DOCUMENT_CHUNK.value,
                        EvidenceType.SEMANTIC_DEFINITION.value,
                        EvidenceType.APPROVED_METRIC.value,
                        EvidenceType.SQL_RESULT.value,
                        "document",
                        "sql",
                        "metric",
                        "definition",
                    }
                    for t in types
                )
            ):
                # Skip if already captured as numeric pair
                already = any(
                    c.get("metric") == claim and c.get("conflict_kind") == "numeric"
                    for c in conflicts
                )
                if already:
                    continue
                a, b = group[0], group[1]
                conflicts.append(
                    {
                        "conflict_kind": "cross_type",
                        "claim": claim,
                        "source_a": a.get("source_name"),
                        "type_a": a.get("evidence_type"),
                        "value_a": a.get("value"),
                        "source_b": b.get("source_name"),
                        "type_b": b.get("evidence_type"),
                        "value_b": b.get("value"),
                    }
                )

        if not conflicts:
            return SourceConflictReport(has_conflict=False)

        # Try resolve via authority + effective dates
        auth_source = self._pick_authority(authority, effective_dates, as_of)
        if auth_source:
            remaining = [
                c
                for c in conflicts
                if auth_source not in {c.get("source_a"), c.get("source_b")}
            ]
            # If authority participates, treat as resolved
            if any(
                auth_source in {c.get("source_a"), c.get("source_b")} for c in conflicts
            ):
                return SourceConflictReport(
                    has_conflict=True,
                    conflicts=conflicts,
                    resolved=True,
                    resolved_by=auth_source,
                    status=None,
                    notes=[f"resolved_by_authority:{auth_source}"],
                )
            if not remaining:
                return SourceConflictReport(
                    has_conflict=True,
                    conflicts=conflicts,
                    resolved=True,
                    resolved_by=auth_source,
                    status=None,
                )

        return SourceConflictReport(
            has_conflict=True,
            conflicts=conflicts,
            resolved=False,
            status="SOURCE_CONFLICT",
            notes=["unresolved_multi_source_disagreement"],
        )

    def _pick_authority(
        self,
        authority: dict[str, Any] | list[dict[str, Any]] | None,
        effective_dates: dict[str, Any] | None,
        as_of: date | datetime | str | None,
    ) -> str | None:
        target = _as_date(as_of)
        rows: list[dict[str, Any]]
        if authority is None:
            rows = []
        elif isinstance(authority, dict):
            rows = [authority]
        else:
            rows = list(authority)

        best: tuple[int, int, str] | None = None
        for row in rows:
            name = str(row.get("source_name") or row.get("name") or "")
            if not name:
                continue
            if target is not None:
                start = _as_date(row.get("effective_from"))
                end = _as_date(row.get("effective_to"))
                if effective_dates and name in effective_dates:
                    ed = effective_dates[name]
                    start = _as_date(ed.get("effective_from")) or start
                    end = _as_date(ed.get("effective_to")) or end
                if start and target < start:
                    continue
                if end and target >= end:
                    continue
            level = AUTHORITY_RANK.get(str(row.get("authority_level") or "").lower(), 0)
            priority = int(row.get("priority") or 0)
            cand = (level, priority, name)
            if best is None or cand[:2] > best[:2]:
                best = cand
        return best[2] if best else None

    @staticmethod
    def _normalize(evidence: EvidenceObject | dict[str, Any]) -> dict[str, Any]:
        if isinstance(evidence, EvidenceObject):
            return {
                "source_name": evidence.source_name,
                "evidence_type": evidence.type.value,
                "value": evidence.value,
                "claim_key": (evidence.metadata or {}).get("metric")
                or (evidence.metadata or {}).get("claim_key"),
                "metric": (evidence.metadata or {}).get("metric"),
                "authority_level": evidence.authority_level,
            }
        return {
            "source_name": evidence.get("source_name") or evidence.get("source"),
            "evidence_type": str(
                evidence.get("evidence_type") or evidence.get("type") or ""
            ),
            "value": evidence.get("value") or evidence.get("content"),
            "claim_key": evidence.get("claim_key") or evidence.get("metric"),
            "metric": evidence.get("metric"),
            "authority_level": evidence.get("authority_level"),
        }

    @staticmethod
    def _value_fingerprint(row: dict[str, Any]) -> str | None:
        value = row.get("value")
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return f"num:{round(float(value), 6)}"
        text = str(value).strip().lower()
        return f"txt:{text}" if text else None

# =============================================================================
# Domain Layer — Critique + bounded debate (Phase 6)
# =============================================================================
# El Critic NO genera otra respuesta: produce un CritiqueReport con problemas
# concretos (claims sin evidencia, citas débiles, supuestos temporales,
# conflictos no resueltos). El debate es acotado:
#
#   PROPOSAL (claim) → CHALLENGE (issue) → RESPONSE + EVIDENCE CHECK →
#   RESOLUTION (defended | upheld | escalated)
#
# Reglas:
#   - Máximo N rondas (CognitiveBudget.max_debate_rounds); 0 = sin debate.
#   - Un challenge recibe UNA sola respuesta: no hay ping-pong ni chat libre.
#   - Nada se auto-resuelve: `upheld` degrada el claim con `requires_review`.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.core.domain.evidence import ClaimRecord, ClaimVerificationStatus, EvidenceRecord
from src.core.domain.temporal_conflict import ClaimTemporalState

_MIN_EXCERPT_CHARS = 80
_MIN_RETRIEVAL_SCORE = 0.3
_DEFENDED_RATIO = 0.25


class CritiqueIssueKind(StrEnum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_EVIDENCE = "missing_evidence"
    WEAK_CITATION = "weak_citation"
    TEMPORAL_ASSUMPTION = "temporal_assumption"
    UNRESOLVED_CONFLICT = "unresolved_conflict"


class DebateOutcomeKind(StrEnum):
    DEFENDED = "defended"
    UPHELD = "upheld"
    ESCALATED = "escalated"


@dataclass(frozen=True, kw_only=True)
class CritiqueIssue:
    kind: CritiqueIssueKind
    claim_id: UUID | None = None
    detail: str = ""
    severity: str = "medium"  # low | medium | high

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "claim_id": str(self.claim_id) if self.claim_id else None,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass(frozen=True, kw_only=True)
class CritiqueReport:
    issues: tuple[CritiqueIssue, ...] = ()
    checked_claims: int = 0
    unsupported: int = 0
    missing_evidence: int = 0
    weak_citations: int = 0
    temporal_assumptions: int = 0
    unresolved_conflicts: int = 0
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "issues": [issue.to_dict() for issue in self.issues],
            "checked_claims": self.checked_claims,
            "unsupported": self.unsupported,
            "missing_evidence": self.missing_evidence,
            "weak_citations": self.weak_citations,
            "temporal_assumptions": self.temporal_assumptions,
            "unresolved_conflicts": self.unresolved_conflicts,
            "summary": self.summary,
        }


@dataclass(frozen=True, kw_only=True)
class DebateOutcome:
    challenge: CritiqueIssue
    claim_id: UUID
    evidence_check_ratio: float
    kind: DebateOutcomeKind
    resolution_note: str = ""
    requires_review: bool = False

    def to_dict(self) -> dict:
        return {
            "challenge": self.challenge.to_dict(),
            "claim_id": str(self.claim_id),
            "evidence_check_ratio": round(self.evidence_check_ratio, 4),
            "kind": self.kind.value,
            "resolution_note": self.resolution_note,
            "requires_review": self.requires_review,
        }


def evidence_support_ratio(claim_text: str, excerpt: str) -> float:
    """Token overlap claim↔evidencia (determinista, compartido con verifier)."""
    claim_tokens = {
        token
        for token in re.findall(r"\w+", " ".join((claim_text or "").lower().split()))
        if len(token) > 2
    }
    if not claim_tokens:
        return 0.0
    excerpt_tokens = set(re.findall(r"\w+", (excerpt or "").lower()))
    return len(claim_tokens & excerpt_tokens) / len(claim_tokens)


def build_critique(
    *,
    claims: list[ClaimRecord],
    evidence: list[EvidenceRecord],
    temporal: dict[UUID, ClaimTemporalState],
    conflicts: list[dict],
    now: datetime | None = None,
) -> CritiqueReport:
    """Deterministic critique over claims/evidence/temporal/conflicts."""
    evidence_by_id = {record.id: record for record in evidence}
    issues: list[CritiqueIssue] = []
    counts = {
        "unsupported": 0,
        "missing_evidence": 0,
        "weak_citations": 0,
        "temporal_assumptions": 0,
        "unresolved_conflicts": 0,
    }

    for claim in claims:
        if claim.status is ClaimVerificationStatus.CONFLICTED:
            continue
        if claim.status is ClaimVerificationStatus.UNSUPPORTED:
            counts["unsupported"] += 1
            issues.append(
                CritiqueIssue(
                    kind=CritiqueIssueKind.UNSUPPORTED_CLAIM,
                    claim_id=claim.id,
                    detail=f"'{claim.text[:160]}' está UNSUPPORTED",
                    severity="high",
                )
            )
        if not claim.evidence_ids:
            counts["missing_evidence"] += 1
            issues.append(
                CritiqueIssue(
                    kind=CritiqueIssueKind.MISSING_EVIDENCE,
                    claim_id=claim.id,
                    detail=f"'{claim.text[:160]}' no tiene evidencia adjunta",
                    severity="high",
                )
            )
        else:
            excerpts = [
                evidence_by_id[eid]
                for eid in claim.evidence_ids
                if eid in evidence_by_id
            ]
            weak = (
                not excerpts
                or any(
                    len(record.excerpt or "") < _MIN_EXCERPT_CHARS
                    or (
                        record.retrieval_score is not None
                        and record.retrieval_score < _MIN_RETRIEVAL_SCORE
                    )
                    for record in excerpts
                )
            )
            if weak:
                counts["weak_citations"] += 1
                issues.append(
                    CritiqueIssue(
                        kind=CritiqueIssueKind.WEAK_CITATION,
                        claim_id=claim.id,
                        detail=f"'{claim.text[:160]}' depende de citas débiles",
                        severity="medium",
                    )
                )
        if temporal.get(claim.id) is ClaimTemporalState.HISTORICAL:
            counts["temporal_assumptions"] += 1
            issues.append(
                CritiqueIssue(
                    kind=CritiqueIssueKind.TEMPORAL_ASSUMPTION,
                    claim_id=claim.id,
                    detail=(
                        f"'{claim.text[:160]}' usa información histórica "
                        f"(scope={claim.temporal_scope})"
                    ),
                    severity="medium",
                )
            )

    for conflict in conflicts:
        claim_ids = conflict.get("claims") or []
        counts["unresolved_conflicts"] += 1
        issues.append(
            CritiqueIssue(
                kind=CritiqueIssueKind.UNRESOLVED_CONFLICT,
                claim_id=UUID(str(claim_ids[0])) if claim_ids else None,
                detail=str(conflict.get("reason") or "conflicto sin resolver"),
                severity="high",
            )
        )

    summary = (
        f"Critique: {counts['unsupported']} unsupported, "
        f"{counts['missing_evidence']} sin evidencia, "
        f"{counts['weak_citations']} citas débiles, "
        f"{counts['temporal_assumptions']} supuestos temporales, "
        f"{counts['unresolved_conflicts']} conflictos sin resolver"
    )
    return CritiqueReport(
        issues=tuple(issues),
        checked_claims=len(claims),
        summary=summary,
        **counts,
    )


def run_debate_round(
    *,
    report: CritiqueReport,
    claims: dict[UUID, ClaimRecord],
    evidence: list[EvidenceRecord],
    max_rounds: int,
) -> tuple[DebateOutcome, ...]:
    """One bounded round: each challenged claim gets exactly one response."""
    if max_rounds < 1 or not report.issues:
        return ()
    evidence_by_id = {record.id: record for record in evidence}
    outcomes: list[DebateOutcome] = []
    debated: set[UUID] = set()
    for issue in report.issues:
        if issue.claim_id is None or issue.claim_id in debated:
            continue
        claim = claims.get(issue.claim_id)
        if claim is None:
            continue
        debated.add(issue.claim_id)
        excerpts = [
            evidence_by_id[eid].excerpt
            for eid in claim.evidence_ids
            if eid in evidence_by_id
        ]
        ratio = max(
            (
                evidence_support_ratio(claim.text, excerpt)
                for excerpt in excerpts
            ),
            default=0.0,
        )
        if ratio >= _DEFENDED_RATIO:
            kind = DebateOutcomeKind.DEFENDED
            note = "claim defendido: la evidencia sostiene la afirmación"
        else:
            kind = DebateOutcomeKind.UPHELD
            note = "challenge sostenido: evidencia insuficiente"
        outcomes.append(
            DebateOutcome(
                challenge=issue,
                claim_id=claim.id,
                evidence_check_ratio=ratio,
                kind=kind,
                resolution_note=note,
                requires_review=kind is DebateOutcomeKind.UPHELD,
            )
        )
    return tuple(outcomes)

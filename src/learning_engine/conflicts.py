# =============================================================================
# Conflictos de claims. El documento más nuevo no gana solo.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(kw_only=True)
class ClaimView:
    organization_id: UUID
    subject: str
    predicate: str
    object_value: str
    source: str
    claim_id: UUID = field(default_factory=uuid4)
    authority: str | None = None
    freshness: datetime | None = None
    effective_date: datetime | None = None
    version: int | None = None


@dataclass(kw_only=True)
class Conflict:
    organization_id: UUID
    subject: str
    predicate: str
    claims: list[dict]
    suggestion: str = "human_review"
    id: UUID = field(default_factory=uuid4)
    status: str = "open"
    resolved_by: UUID | None = None
    chosen_claim_id: UUID | None = None
    reason: str = ""
    resolved_at: datetime | None = None

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "subject": self.subject,
            "predicate": self.predicate,
            "claims": list(self.claims),
            "suggestion": self.suggestion,
            "status": self.status,
            "resolved_by": str(self.resolved_by) if self.resolved_by else None,
            "chosen_claim_id": str(self.chosen_claim_id) if self.chosen_claim_id else None,
            "reason": self.reason,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "auto_resolved": False,
        }


def detect_conflicts(claims: list[ClaimView]) -> list[Conflict]:
    groups: dict[tuple[str, str, str], list[ClaimView]] = {}
    for claim in claims:
        key = (str(claim.organization_id), claim.subject.strip().lower(), claim.predicate.strip().lower())
        groups.setdefault(key, []).append(claim)
    found: list[Conflict] = []
    for group in groups.values():
        objects = {item.object_value.strip().lower() for item in group}
        sources = {item.source.strip().lower() for item in group}
        if len(objects) < 2 or len(sources) < 2:
            continue
        found.append(
            Conflict(
                organization_id=group[0].organization_id,
                subject=group[0].subject,
                predicate=group[0].predicate,
                claims=[_claim_dict(item) for item in group],
                suggestion="human_review",
            )
        )
    return found


def resolve_conflict(
    conflict: Conflict,
    *,
    actor_id: UUID,
    chosen_claim_id: UUID,
    reason: str,
) -> Conflict:
    known = {item["claim_id"] for item in conflict.claims}
    if str(chosen_claim_id) not in known:
        raise ValueError("chosen claim is not part of the conflict")
    if not reason.strip():
        raise ValueError("resolution requires a reason")
    conflict.status = "resolved"
    conflict.resolved_by = actor_id
    conflict.chosen_claim_id = chosen_claim_id
    conflict.reason = reason.strip()[:500]
    conflict.resolved_at = _utcnow()
    return conflict


def _claim_dict(claim: ClaimView) -> dict:
    return {
        "claim_id": str(claim.claim_id),
        "object": claim.object_value,
        "source": claim.source,
        "authority": claim.authority,
        "freshness": claim.freshness.isoformat() if claim.freshness else None,
        "effective_date": claim.effective_date.isoformat() if claim.effective_date else None,
        "version": claim.version,
    }

# =============================================================================
# Domain Layer — Knowledge Curator (Phase 7)
# =============================================================================
# El Curator NO responde preguntas: convierte observaciones (conflictos,
# debates, correcciones) en KnowledgeSuggestion para revisión humana.
#
# Leyes:
#   - Toda sugerencia nace PROPOSED y con provenance INFERRED/OBSERVED.
#   - APPROVED exige `decided_by` (revisión humana explícita); jamás se
#     auto-aprueba una inferencia (brief §48/§49).
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SuggestionKind(StrEnum):
    GLOSSARY_TERM = "glossary_term"
    SYNONYM = "synonym"
    BUSINESS_RULE = "business_rule"
    RELATIONSHIP = "relationship"
    CONCEPT_REVIEW = "concept_review"
    FACT_CANDIDATE = "fact_candidate"


class SuggestionStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class CuratorDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


@dataclass(frozen=True, kw_only=True)
class KnowledgeSuggestion:
    organization_id: UUID
    kind: SuggestionKind
    title: str
    reasoning: str = ""
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    run_id: UUID | None = None
    claim_ids: tuple[UUID, ...] = ()
    payload: dict = field(default_factory=dict)
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    status: SuggestionStatus = SuggestionStatus.PROPOSED
    confidence: float = 0.0
    created_by: UUID | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("KnowledgeSuggestion.title must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("KnowledgeSuggestion.confidence must be within [0, 1]")
        if self.status is SuggestionStatus.APPROVED and self.decided_by is None:
            raise ValueError(
                "APPROVED suggestion requires decided_by (human review is the "
                "only promotion path)"
            )
        if self.status is not SuggestionStatus.PROPOSED and self.decided_at is None:
            raise ValueError("decided suggestions require decided_at")

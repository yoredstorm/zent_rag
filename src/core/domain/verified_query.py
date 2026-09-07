# =============================================================================
# Domain — Verified Query Repository (Phase 26C)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class VerifiedQueryStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VERIFIED = "VERIFIED"
    DEPRECATED = "DEPRECATED"
    INVALID = "INVALID"


class MappingSuggestionStatus(StrEnum):
    """Governed learning for inferred physical mappings (never auto-promote)."""

    INFERRED = "INFERRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EDITED_APPROVED = "EDITED_APPROVED"


@dataclass(kw_only=True)
class VerifiedQuery:
    """Organization-validated NL↔SQL knowledge artifact."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    name: str
    description: str = ""
    canonical_question: str
    question_variants: list[str] = field(default_factory=list)
    semantic_ast: dict[str, Any] = field(default_factory=dict)
    verified_sql: str
    dialect: str = "postgres"
    source_ids: list[str] = field(default_factory=list)
    table_dependencies: list[str] = field(default_factory=list)
    column_dependencies: list[str] = field(default_factory=list)
    metric_dependencies: list[str] = field(default_factory=list)
    concept_dependencies: list[str] = field(default_factory=list)
    status: VerifiedQueryStatus = VerifiedQueryStatus.DRAFT
    version: int = 1
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_verified_at: datetime | None = None
    execution_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "name": self.name,
            "description": self.description,
            "canonical_question": self.canonical_question,
            "question_variants": list(self.question_variants),
            "semantic_ast": dict(self.semantic_ast),
            "verified_sql": self.verified_sql,
            "dialect": self.dialect,
            "source_ids": list(self.source_ids),
            "table_dependencies": list(self.table_dependencies),
            "column_dependencies": list(self.column_dependencies),
            "metric_dependencies": list(self.metric_dependencies),
            "concept_dependencies": list(self.concept_dependencies),
            "status": self.status.value if isinstance(self.status, VerifiedQueryStatus) else self.status,
            "version": self.version,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_verified_at": (
                self.last_verified_at.isoformat() if self.last_verified_at else None
            ),
            "execution_fingerprint": self.execution_fingerprint,
        }


@dataclass(kw_only=True)
class VerifiedQueryMatch:
    """Search hit — similarity must consider AST, not only text."""

    query: VerifiedQuery
    score: float
    signals: dict[str, float] = field(default_factory=dict)
    adaptable: bool = False
    adaptation_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "score": self.score,
            "signals": dict(self.signals),
            "adaptable": self.adaptable,
            "adaptation_notes": list(self.adaptation_notes),
        }


@dataclass(kw_only=True)
class MappingSuggestion:
    """Inferred physical mapping from successful SQL — requires human review."""

    id: UUID = field(default_factory=uuid4)
    organization_id: UUID
    concept: str
    entity_type: str = "ENTITY"
    physical_predicate: str
    evidence_count: int = 0
    evidence_sample: list[str] = field(default_factory=list)
    status: MappingSuggestionStatus = MappingSuggestionStatus.INFERRED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "organization_id": str(self.organization_id),
            "concept": self.concept,
            "entity_type": self.entity_type,
            "physical_predicate": self.physical_predicate,
            "evidence_count": self.evidence_count,
            "evidence_sample": list(self.evidence_sample),
            "status": self.status.value if isinstance(self.status, MappingSuggestionStatus) else self.status,
            "created_at": self.created_at.isoformat(),
            "reviewed_by": str(self.reviewed_by) if self.reviewed_by else None,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }

# =============================================================================
# Domain Layer — Evidence + Claim Ledger (Phase 2)
# =============================================================================
# Objetos de primera clase del Cognitive OS:
#   - EvidenceRecord: un fragmento localizable que sustenta conocimiento
#     (documento/página/sección/bloque/tabla/fila o referencia de base de datos)
#     con provenance de retrieval (score dense/hybrid, reranker) y autoridad.
#   - ClaimRecord: una afirmación extraída o propuesta por un agente, con
#     normalización sujeto/predicado/objeto para detección estructural de
#     contradicciones entre fuentes o entre agentes.
#
# Leyes:
#   - Evidencia es ledger append-only: nunca se muta, se agrega.
#   - Un claim PROPOSED no es verdad; los estados de verificación son
#     explícitos (proposed/supported/partially_supported/unsupported/
#     conflicted/outdated).
#   - La evidencia adjunta vive en evidence_ids y solo se modifica por
#     attach_evidence (un upsert de claim no la pisa).
#
# Tipos puros, sin I/O. Persistencia: migración 103 (evidence_ledger +
# claim_ledger). Adapter en infrastructure/postgres/evidence_ledger.py.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClaimVerificationStatus(StrEnum):
    """Verification lifecycle of a claim (brief §20/§28).

    PROPOSED is the only state a claim can be created in by an agent;
    verification moves it to the other states. `supported` means at least
    one piece of evidence sustains it, never that a human approved it.
    """

    PROPOSED = "proposed"
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONFLICTED = "conflicted"
    OUTDATED = "outdated"


@dataclass(frozen=True, kw_only=True)
class EvidenceRecord:
    """A locatable piece of evidence backing knowledge.

    Immutable ledger entry. `content_hash` identifies the exact excerpt
    content so duplicate evidence can be detected without string compare.
    """

    organization_id: UUID
    excerpt: str
    content_hash: str
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    corpus_id: UUID | None = None
    source_id: UUID | None = None
    document_id: UUID | None = None
    section_id: UUID | None = None
    block_id: UUID | None = None
    chunk_id: UUID | None = None
    canonical_id: UUID | None = None
    page: int | None = None
    section_path: tuple[str, ...] = ()
    table_reference: str | None = None
    row_reference: str | None = None
    database_reference: str | None = None
    version: int = 1
    effective_date: datetime | None = None
    authority: str | None = None
    retrieval_score: float | None = None
    reranker_score: float | None = None
    agent_id: UUID | None = None
    task_id: UUID | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.excerpt.strip():
            raise ValueError("EvidenceRecord.excerpt must not be empty")
        if not self.content_hash.strip():
            raise ValueError("EvidenceRecord.content_hash must not be empty")
        if self.page is not None and self.page < 1:
            raise ValueError(f"EvidenceRecord.page must be >= 1, got {self.page}")
        if self.version < 1:
            raise ValueError(f"EvidenceRecord.version must be >= 1, got {self.version}")


@dataclass(frozen=True, kw_only=True)
class ClaimRecord:
    """A claim with normalized subject/predicate/object for conflict detection.

    Two claims with the same normalized subject+predicate but different
    normalized object are structurally conflicting; verification decides
    which one holds (authority, temporal validity, evidence quality).
    """

    organization_id: UUID
    text: str
    normalized_subject: str
    normalized_predicate: str
    normalized_object: str | None = None
    id: UUID = field(default_factory=uuid4)
    workspace_id: UUID | None = None
    canonical_id: UUID | None = None
    status: ClaimVerificationStatus = ClaimVerificationStatus.PROPOSED
    confidence: float = 0.0
    evidence_ids: tuple[UUID, ...] = ()
    provenance: CatalogProvenance = CatalogProvenance.INFERRED
    agent_id: UUID | None = None
    task_id: UUID | None = None
    temporal_scope: str | None = None
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("ClaimRecord.text must not be empty")
        if not self.normalized_subject.strip():
            raise ValueError("ClaimRecord.normalized_subject must not be empty")
        if not self.normalized_predicate.strip():
            raise ValueError("ClaimRecord.normalized_predicate must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("ClaimRecord.confidence must be within [0, 1]")

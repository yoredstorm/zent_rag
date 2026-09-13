# =============================================================================
# Ports — Evidence + Claim Ledger (Phase 2)
# =============================================================================
# Evidencia append-only y claims con verificación. organization_id es
# OBLIGATORIO en toda operación; nunca devolver ni adjuntar objetos de otro
# tenant.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.evidence import ClaimRecord, EvidenceRecord


class EvidenceLedgerRepository(ABC):
    """Puerto del ledger de evidencia (append-only)."""

    @abstractmethod
    async def append(self, evidence: EvidenceRecord) -> EvidenceRecord:
        """Registra evidencia. Inmutable: no existe update."""
        ...

    @abstractmethod
    async def get(
        self, organization_id: UUID, evidence_id: UUID
    ) -> EvidenceRecord | None:
        """Evidencia o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def list_for_document(
        self, organization_id: UUID, document_id: UUID, limit: int = 100
    ) -> list[EvidenceRecord]:
        """Evidencia localizada en un documento (scoped)."""
        ...


class ClaimLedgerRepository(ABC):
    """Puerto del ledger de claims (afirmaciones + verificación)."""

    @abstractmethod
    async def upsert(self, claim: ClaimRecord) -> ClaimRecord:
        """Inserta o actualiza el claim por id (org-scoped).

        Nunca pisa `evidence_ids`: la evidencia solo se adjunta con
        `attach_evidence`.
        """
        ...

    @abstractmethod
    async def get(
        self, organization_id: UUID, claim_id: UUID
    ) -> ClaimRecord | None:
        """Claim o None. Nunca cruza organization_id."""
        ...

    @abstractmethod
    async def list_by_subject(
        self, organization_id: UUID, normalized_subject: str, limit: int = 50
    ) -> list[ClaimRecord]:
        """Claims del mismo sujeto normalizado (scoped)."""
        ...

    @abstractmethod
    async def find_conflicting(
        self,
        organization_id: UUID,
        normalized_subject: str,
        normalized_predicate: str,
        normalized_object: str | None,
    ) -> list[ClaimRecord]:
        """Claims con mismo sujeto+predicado y objeto distinto (incluye NULL).

        Detección estructural de contradicciones (brief §16); la resolución
        por autoridad/temporalidad es fase posterior.
        """
        ...

    @abstractmethod
    async def attach_evidence(
        self, organization_id: UUID, claim_id: UUID, evidence_id: UUID
    ) -> ClaimRecord:
        """Adjunta evidencia al claim (idempotente).

        Rechaza con ValueError si el claim o la evidencia no pertenecen a la
        organización.
        """
        ...

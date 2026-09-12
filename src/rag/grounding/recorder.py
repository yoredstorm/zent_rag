# =============================================================================
# Grounding → Evidence Ledger (Phase 2 slice 2)
# =============================================================================
# Productor de evidencia: cada GroundedAnswer aporta sus citas al ledger
# append-only, con locators completos (documento/página/sección/chunk) para
# que claims y verificadores posteriores apunten a evidencia real.
#
# Sin acoplamiento a infraestructura: depende solo del puerto
# EvidenceLedgerRepository (DI). Los fallos del ledger no deben romper la
# respuesta; el llamador decide el try/except.
# =============================================================================
from __future__ import annotations

import hashlib
from uuid import UUID

from src.core.domain.evidence import EvidenceRecord
from src.core.ports.evidence import EvidenceLedgerRepository
from src.rag.grounding.models import GroundedAnswer


class GroundingLedgerRecorder:
    """Persiste la evidencia de un GroundedAnswer en el Evidence Ledger."""

    def __init__(self, evidence_repo: EvidenceLedgerRepository) -> None:
        self._evidence = evidence_repo

    async def record_evidence(
        self,
        *,
        organization_id: UUID,
        answer: GroundedAnswer,
        workspace_id: UUID | None = None,
        agent_id: UUID | None = None,
        task_id: UUID | None = None,
    ) -> list[UUID]:
        """Agrega una fila de evidencia por cita con excerpt no vacío."""
        evidence_ids: list[UUID] = []
        for citation in answer.citations:
            excerpt = citation.excerpt.strip()
            if not excerpt:
                continue
            record = EvidenceRecord(
                organization_id=organization_id,
                excerpt=excerpt,
                content_hash=hashlib.sha256(
                    excerpt.encode("utf-8")
                ).hexdigest(),
                workspace_id=workspace_id,
                source_id=citation.source_id,
                document_id=citation.document_id,
                block_id=citation.block_id,
                chunk_id=citation.chunk_id,
                page=citation.page,
                section_path=citation.section_path,
                retrieval_score=citation.relevance,
                agent_id=agent_id,
                task_id=task_id,
                metadata={
                    "document_name": citation.document_name,
                    "locator": citation.locator,
                },
            )
            saved = await self._evidence.append(record)
            evidence_ids.append(saved.id)
        return evidence_ids

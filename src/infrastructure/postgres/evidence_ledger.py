# =============================================================================
# Evidence + Claim Ledger — Postgres (Phase 2)
# =============================================================================
# evidence_ledger.append() es la única escritura de evidencia (inmutable).
# claim_ledger.upsert() actualiza verificación pero NUNCA pisa evidence_ids;
# la evidencia se adjunta solo con attach_evidence (org-scoped).
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.evidence import (
    ClaimRecord,
    ClaimVerificationStatus,
    EvidenceRecord,
)
from src.core.ports.evidence import ClaimLedgerRepository, EvidenceLedgerRepository
from src.infrastructure.postgres.session import get_async_session

_EVIDENCE_COLUMNS = (
    "id, organization_id, workspace_id, corpus_id, source_id, document_id, "
    "section_id, block_id, chunk_id, canonical_id, page, section_path, "
    "table_reference, row_reference, database_reference, excerpt, content_hash, "
    "version, effective_date, authority, retrieval_score, reranker_score, "
    "agent_id, task_id, metadata, created_at"
)

_CLAIM_COLUMNS = (
    "id, organization_id, workspace_id, canonical_id, text, "
    "normalized_subject, normalized_predicate, normalized_object, status, "
    "confidence, evidence_ids, provenance, agent_id, task_id, temporal_scope, "
    "metadata, created_at, updated_at"
)


class PostgresEvidenceLedgerRepository(EvidenceLedgerRepository):

    async def append(self, evidence: EvidenceRecord) -> EvidenceRecord:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO evidence_ledger ({_EVIDENCE_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :corpus_id,
                        :source_id, :document_id, :section_id, :block_id,
                        :chunk_id, :canonical_id, :page,
                        CAST(:section_path AS jsonb), :table_reference,
                        :row_reference, :database_reference, :excerpt,
                        :content_hash, :version, :effective_date, :authority,
                        :retrieval_score, :reranker_score, :agent_id, :task_id,
                        CAST(:metadata AS jsonb), now()
                    )
                    RETURNING {_EVIDENCE_COLUMNS}
                    """
                ),
                {
                    "id": str(evidence.id),
                    "organization_id": str(evidence.organization_id),
                    "workspace_id": _uuid_or_none(evidence.workspace_id),
                    "corpus_id": _uuid_or_none(evidence.corpus_id),
                    "source_id": _uuid_or_none(evidence.source_id),
                    "document_id": _uuid_or_none(evidence.document_id),
                    "section_id": _uuid_or_none(evidence.section_id),
                    "block_id": _uuid_or_none(evidence.block_id),
                    "chunk_id": _uuid_or_none(evidence.chunk_id),
                    "canonical_id": _uuid_or_none(evidence.canonical_id),
                    "page": evidence.page,
                    "section_path": json.dumps(list(evidence.section_path)),
                    "table_reference": evidence.table_reference,
                    "row_reference": evidence.row_reference,
                    "database_reference": evidence.database_reference,
                    "excerpt": evidence.excerpt,
                    "content_hash": evidence.content_hash,
                    "version": evidence.version,
                    "effective_date": evidence.effective_date,
                    "authority": evidence.authority,
                    "retrieval_score": evidence.retrieval_score,
                    "reranker_score": evidence.reranker_score,
                    "agent_id": _uuid_or_none(evidence.agent_id),
                    "task_id": _uuid_or_none(evidence.task_id),
                    "metadata": json.dumps(evidence.metadata, default=str),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_evidence(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get(
        self, organization_id: UUID, evidence_id: UUID
    ) -> EvidenceRecord | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_EVIDENCE_COLUMNS} FROM evidence_ledger "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(evidence_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_evidence(row) if row is not None else None
        finally:
            await session.close()

    async def list_for_document(
        self, organization_id: UUID, document_id: UUID, limit: int = 100
    ) -> list[EvidenceRecord]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_EVIDENCE_COLUMNS} FROM evidence_ledger "
                    "WHERE organization_id = :oid AND document_id = :did "
                    "ORDER BY created_at, id LIMIT :limit"
                ),
                {
                    "oid": str(organization_id),
                    "did": str(document_id),
                    "limit": limit,
                },
            )
            return [_row_to_evidence(row) for row in result.fetchall()]
        finally:
            await session.close()


class PostgresClaimLedgerRepository(ClaimLedgerRepository):

    async def upsert(self, claim: ClaimRecord) -> ClaimRecord:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"""
                    INSERT INTO claim_ledger ({_CLAIM_COLUMNS})
                    VALUES (
                        :id, :organization_id, :workspace_id, :canonical_id,
                        :text, :normalized_subject, :normalized_predicate,
                        :normalized_object, :status, :confidence,
                        CAST(:evidence_ids AS uuid[]), :provenance, :agent_id,
                        :task_id, :temporal_scope, CAST(:metadata AS jsonb),
                        now(), now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        workspace_id = EXCLUDED.workspace_id,
                        canonical_id = EXCLUDED.canonical_id,
                        text = EXCLUDED.text,
                        normalized_subject = EXCLUDED.normalized_subject,
                        normalized_predicate = EXCLUDED.normalized_predicate,
                        normalized_object = EXCLUDED.normalized_object,
                        status = EXCLUDED.status,
                        confidence = EXCLUDED.confidence,
                        provenance = EXCLUDED.provenance,
                        agent_id = EXCLUDED.agent_id,
                        task_id = EXCLUDED.task_id,
                        temporal_scope = EXCLUDED.temporal_scope,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    RETURNING {_CLAIM_COLUMNS}
                    """
                ),
                {
                    "id": str(claim.id),
                    "organization_id": str(claim.organization_id),
                    "workspace_id": _uuid_or_none(claim.workspace_id),
                    "canonical_id": _uuid_or_none(claim.canonical_id),
                    "text": claim.text,
                    "normalized_subject": claim.normalized_subject,
                    "normalized_predicate": claim.normalized_predicate,
                    "normalized_object": claim.normalized_object,
                    "status": claim.status.value,
                    "confidence": claim.confidence,
                    "evidence_ids": [str(eid) for eid in claim.evidence_ids],
                    "provenance": claim.provenance.value,
                    "agent_id": _uuid_or_none(claim.agent_id),
                    "task_id": _uuid_or_none(claim.task_id),
                    "temporal_scope": claim.temporal_scope,
                    "metadata": json.dumps(claim.metadata, default=str),
                },
            )
            row = result.fetchone()
            await session.commit()
            return _row_to_claim(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def get(
        self, organization_id: UUID, claim_id: UUID
    ) -> ClaimRecord | None:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_CLAIM_COLUMNS} FROM claim_ledger "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(claim_id), "oid": str(organization_id)},
            )
            row = result.fetchone()
            return _row_to_claim(row) if row is not None else None
        finally:
            await session.close()

    async def list_by_subject(
        self, organization_id: UUID, normalized_subject: str, limit: int = 50
    ) -> list[ClaimRecord]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_CLAIM_COLUMNS} FROM claim_ledger "
                    "WHERE organization_id = :oid AND normalized_subject = :subject "
                    "ORDER BY updated_at DESC, id LIMIT :limit"
                ),
                {
                    "oid": str(organization_id),
                    "subject": normalized_subject,
                    "limit": limit,
                },
            )
            return [_row_to_claim(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def find_conflicting(
        self,
        organization_id: UUID,
        normalized_subject: str,
        normalized_predicate: str,
        normalized_object: str | None,
    ) -> list[ClaimRecord]:
        session = await get_async_session()
        try:
            result = await session.execute(
                text(
                    f"SELECT {_CLAIM_COLUMNS} FROM claim_ledger "
                    "WHERE organization_id = :oid "
                    "AND normalized_subject = :subject "
                    "AND normalized_predicate = :predicate "
                    "AND normalized_object IS DISTINCT FROM :object "
                    "ORDER BY updated_at DESC, id"
                ),
                {
                    "oid": str(organization_id),
                    "subject": normalized_subject,
                    "predicate": normalized_predicate,
                    "object": normalized_object,
                },
            )
            return [_row_to_claim(row) for row in result.fetchall()]
        finally:
            await session.close()

    async def attach_evidence(
        self, organization_id: UUID, claim_id: UUID, evidence_id: UUID
    ) -> ClaimRecord:
        session = await get_async_session()
        try:
            claim_exists = await session.execute(
                text(
                    "SELECT 1 FROM claim_ledger "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(claim_id), "oid": str(organization_id)},
            )
            if claim_exists.fetchone() is None:
                raise ValueError("claim not found for this organization")
            evidence_exists = await session.execute(
                text(
                    "SELECT 1 FROM evidence_ledger "
                    "WHERE id = :id AND organization_id = :oid"
                ),
                {"id": str(evidence_id), "oid": str(organization_id)},
            )
            if evidence_exists.fetchone() is None:
                raise ValueError("evidence not found for this organization")

            result = await session.execute(
                text(
                    f"""
                    UPDATE claim_ledger
                    SET evidence_ids = array_append(evidence_ids, :eid),
                        updated_at = now()
                    WHERE id = :id AND organization_id = :oid
                      AND NOT (:eid = ANY(evidence_ids))
                    RETURNING {_CLAIM_COLUMNS}
                    """
                ),
                {
                    "eid": str(evidence_id),
                    "id": str(claim_id),
                    "oid": str(organization_id),
                },
            )
            row = result.fetchone()
            if row is None:
                result = await session.execute(
                    text(
                        f"SELECT {_CLAIM_COLUMNS} FROM claim_ledger "
                        "WHERE id = :id AND organization_id = :oid"
                    ),
                    {"id": str(claim_id), "oid": str(organization_id)},
                )
                row = result.fetchone()
            await session.commit()
            return _row_to_claim(row)
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid_or_none(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _row_to_evidence(row) -> EvidenceRecord:
    return EvidenceRecord(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        corpus_id=row.corpus_id,
        source_id=row.source_id,
        document_id=row.document_id,
        section_id=row.section_id,
        block_id=row.block_id,
        chunk_id=row.chunk_id,
        canonical_id=row.canonical_id,
        page=row.page,
        section_path=tuple(row.section_path or ()),
        table_reference=row.table_reference,
        row_reference=row.row_reference,
        database_reference=row.database_reference,
        excerpt=row.excerpt,
        content_hash=row.content_hash,
        version=row.version,
        effective_date=row.effective_date,
        authority=row.authority,
        retrieval_score=row.retrieval_score,
        reranker_score=row.reranker_score,
        agent_id=row.agent_id,
        task_id=row.task_id,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        created_at=row.created_at,
    )


def _row_to_claim(row) -> ClaimRecord:
    return ClaimRecord(
        id=row.id,
        organization_id=row.organization_id,
        workspace_id=row.workspace_id,
        canonical_id=row.canonical_id,
        text=row.text,
        normalized_subject=row.normalized_subject,
        normalized_predicate=row.normalized_predicate,
        normalized_object=row.normalized_object,
        status=ClaimVerificationStatus(row.status),
        confidence=row.confidence,
        evidence_ids=tuple(row.evidence_ids or ()),
        provenance=CatalogProvenance(row.provenance),
        agent_id=row.agent_id,
        task_id=row.task_id,
        temporal_scope=row.temporal_scope,
        metadata=row.metadata if isinstance(row.metadata, dict) else {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )

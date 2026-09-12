"""Evidence + Claim Ledger — Phase 2 slice 1.

evidence_ledger: fragmentos localizables que sustentan conocimiento
(documento/página/sección/bloque/tabla/fila/db), append-only, con scores de
retrieval y autoridad. claim_ledger: afirmaciones normalizadas
(sujeto/predicado/objeto) con estado de verificación y evidencia adjunta.

Puro aditivo: ningún camino productivo lee estas tablas.

Revision ID: 103
Revises: 102
"""
from __future__ import annotations

from alembic import op

revision: str = "103"
down_revision: str = "102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS evidence_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            corpus_id UUID,
            source_id UUID,
            document_id UUID,
            section_id UUID,
            block_id UUID,
            chunk_id UUID,
            canonical_id UUID REFERENCES knowledge_canonical_objects(id) ON DELETE SET NULL,
            page INTEGER CHECK (page IS NULL OR page >= 1),
            section_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            table_reference TEXT,
            row_reference TEXT,
            database_reference TEXT,
            excerpt TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            effective_date TIMESTAMPTZ,
            authority VARCHAR(32),
            retrieval_score DOUBLE PRECISION,
            reranker_score DOUBLE PRECISION,
            agent_id UUID,
            task_id UUID,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ledger_org_created "
        "ON evidence_ledger(organization_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ledger_org_document "
        "ON evidence_ledger(organization_id, document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_evidence_ledger_org_hash "
        "ON evidence_ledger(organization_id, content_hash)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS claim_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            canonical_id UUID REFERENCES knowledge_canonical_objects(id) ON DELETE SET NULL,
            text TEXT NOT NULL,
            normalized_subject VARCHAR(512) NOT NULL,
            normalized_predicate VARCHAR(512) NOT NULL,
            normalized_object VARCHAR(1024),
            status VARCHAR(24) NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed','supported','partially_supported','unsupported','conflicted','outdated')),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence >= 0 AND confidence <= 1),
            evidence_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
            provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            agent_id UUID,
            task_id UUID,
            temporal_scope VARCHAR(128),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_claim_ledger_org_subject "
        "ON claim_ledger(organization_id, normalized_subject)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_claim_ledger_org_subject_predicate "
        "ON claim_ledger(organization_id, normalized_subject, normalized_predicate)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_claim_ledger_org_created "
        "ON claim_ledger(organization_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claim_ledger")
    op.execute("DROP TABLE IF EXISTS evidence_ledger")

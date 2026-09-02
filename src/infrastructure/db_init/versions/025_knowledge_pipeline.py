"""Knowledge pipeline — data source lifecycle, profiling, index versions,
training runs.

Revision ID: 025
Revises: 024
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Ciclo de vida de la fuente de datos.
    # -------------------------------------------------------------------------
    op.execute(
        "ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_status_check"
    )
    op.execute(
        "UPDATE kb_sources SET status = CASE "
        "WHEN status = 'active' THEN 'ready' "
        "WHEN status = 'disabled' THEN 'connected' "
        "WHEN status = 'error' THEN 'error' "
        "ELSE 'created' END "
        "WHERE status NOT IN ('created', 'connected', 'discovering', 'profiled', "
        "'ready', 'ingesting', 'indexed', 'error')"
    )
    op.execute(
        "ALTER TABLE kb_sources ADD CONSTRAINT kb_sources_status_check "
        "CHECK (status IN ('created', 'connected', 'discovering', 'profiled', "
        "'ready', 'ingesting', 'indexed', 'error'))"
    )

    # -------------------------------------------------------------------------
    # Data Profiling — perfil de columnas/tablas de una fuente.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            source_id UUID NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
            columns JSONB NOT NULL DEFAULT '[]',
            tables JSONB NOT NULL DEFAULT '[]',
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_profiles_source "
        "ON source_profiles(source_id, detected_at DESC)"
    )

    # -------------------------------------------------------------------------
    # Index versions — snapshot del estado del índice por knowledge base.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS index_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            embedding_model VARCHAR(200),
            chunk_size INTEGER,
            chunk_overlap INTEGER,
            vector_count BIGINT NOT NULL DEFAULT 0,
            source_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_index_versions_kb "
        "ON index_versions(knowledge_base_id, created_at DESC)"
    )

    # -------------------------------------------------------------------------
    # Training runs — ejecuciones de pipeline sobre una KB.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS training_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'partial')),
            current_step VARCHAR(30) NOT NULL DEFAULT 'preparation',
            progress INTEGER NOT NULL DEFAULT 0,
            rows_processed BIGINT NOT NULL DEFAULT 0,
            vectors_upserted BIGINT NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_runs_org "
        "ON training_runs(organization_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs ADD COLUMN IF NOT EXISTS training_run_id UUID "
        "REFERENCES training_runs(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_training "
        "ON ingestion_jobs(training_run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ingestion_jobs_training")
    op.execute("ALTER TABLE ingestion_jobs DROP COLUMN IF EXISTS training_run_id")
    op.execute("DROP TABLE IF EXISTS training_runs")
    op.execute("DROP TABLE IF EXISTS index_versions")
    op.execute("DROP TABLE IF EXISTS source_profiles")
    op.execute(
        "ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_status_check"
    )
    op.execute(
        "ALTER TABLE kb_sources ADD CONSTRAINT kb_sources_status_check "
        "CHECK (status IN ('active', 'disabled', 'error'))"
    )

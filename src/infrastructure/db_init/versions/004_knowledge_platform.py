"""Knowledge Platform — KB config, sources, ingestion jobs (durable).

Revision ID: 004
Revises: 003
Create Date: 2026-08-20

Extiende knowledge_bases con configuración de chunking/retrieval y crea el
subsistema de ingestion durable:
- kb_sources: fuentes de una KB (sql, file, csv, excel, web, s3, api)
- ingestion_jobs: estado real de jobs (Postgres source of truth; Redis = wakeup)
- ingestion_job_errors: historial de fallos por intento
- source_sync_state: cursor incremental por fuente
- source_documents: registry para update/delete detection

Los scripts de db_init/ (02-rbac.sql, 05-platform-resources.sql y
06-knowledge-platform.sql) ya contienen el esquema final para bases nuevas;
esta migración es idempotente y transforma bases existentes.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. knowledge_bases: configuración de chunking / retrieval
    for col, ddl in (
        ("chunking_strategy",
         "ALTER TABLE knowledge_bases ADD COLUMN chunking_strategy VARCHAR(20) NOT NULL DEFAULT 'fixed'"),
        ("chunk_size",
         "ALTER TABLE knowledge_bases ADD COLUMN chunk_size INTEGER NOT NULL DEFAULT 1200"),
        ("chunk_overlap",
         "ALTER TABLE knowledge_bases ADD COLUMN chunk_overlap INTEGER NOT NULL DEFAULT 150"),
        ("retrieval_strategy",
         "ALTER TABLE knowledge_bases ADD COLUMN retrieval_strategy VARCHAR(20) NOT NULL DEFAULT 'vector'"),
        ("reranker",
         "ALTER TABLE knowledge_bases ADD COLUMN reranker VARCHAR(50)"),
        ("metadata_schema",
         "ALTER TABLE knowledge_bases ADD COLUMN metadata_schema JSONB NOT NULL DEFAULT '{}'"),
    ):
        # Las comillas simples van duplicadas: el DDL se pasa como literal
        # dentro de un EXECUTE en un bloque DO $$ ... $$.
        ddl_escaped = ddl.replace("'", "''")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'knowledge_bases' AND column_name = '{col}'
                ) THEN
                    EXECUTE '{ddl_escaped}';
                END IF;
            END $$;
            """
        )

    # 2. Tablas del subsistema de ingestion (idempotentes)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_sources (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            knowledge_base_id UUID REFERENCES knowledge_bases(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            type VARCHAR(40) NOT NULL,
            config_json JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'disabled', 'error')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, name)
        )
        """
    )
    # Registro de conectores extensible: se elimina el CHECK de tipo (si la
    # tabla legacy lo traía) para que nuevas fuentes no requieran migración.
    op.execute(
        "ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_type_check"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_sources_organization ON kb_sources(organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(knowledge_base_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_jobs (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            knowledge_base_id UUID REFERENCES knowledge_bases(id) ON DELETE SET NULL,
            source_id UUID REFERENCES kb_sources(id) ON DELETE SET NULL,
            job_type VARCHAR(40) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'dead', 'canceled')),
            progress INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            records_processed BIGINT NOT NULL DEFAULT 0,
            records_failed BIGINT NOT NULL DEFAULT 0,
            error_summary JSONB NOT NULL DEFAULT '{}',
            cursor_snapshot JSONB,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            retry_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_org ON ingestion_jobs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_source ON ingestion_jobs(source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_due ON ingestion_jobs(status, retry_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_job_errors (
            id BIGSERIAL PRIMARY KEY,
            job_id UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
            attempt INTEGER NOT NULL,
            error TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_errors_job ON ingestion_job_errors(job_id, attempt)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_sync_state (
            source_id UUID PRIMARY KEY REFERENCES kb_sources(id) ON DELETE CASCADE,
            cursor_json JSONB,
            last_success_at TIMESTAMPTZ,
            last_error TEXT,
            last_processed_count BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_documents (
            id BIGSERIAL PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
            external_id TEXT NOT NULL,
            document_id UUID NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'deleted')),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source_id, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_documents_source ON source_documents(source_id, status)"
    )

    # 3. Permisos nuevos: sources:read / sources:write
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000021', 'sources:read', 'Ver fuentes de datos'),
            ('40000000-0000-0000-0000-000000000022', 'sources:write', 'Crear/editar/sincronizar fuentes de datos')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name IN ('owner', 'admin', 'member')
          AND p.code IN ('sources:read', 'sources:write')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'viewer'
          AND p.code = 'sources:read'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_documents")
    op.execute("DROP TABLE IF EXISTS source_sync_state")
    op.execute("DROP TABLE IF EXISTS ingestion_job_errors")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS kb_sources")
    for col in ("metadata_schema", "reranker", "retrieval_strategy",
                "chunk_overlap", "chunk_size", "chunking_strategy"):
        op.execute(f"ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS {col}")

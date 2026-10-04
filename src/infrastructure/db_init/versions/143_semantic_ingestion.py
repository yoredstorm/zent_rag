"""Progressive Semantic Ingestion — manifiesto de cobertura + ventanas.

Dos tablas:

1. ``knowledge_ingestion_manifests``: una fila por (organización, fuente,
   external_id). Responde «¿ZENT procesó realmente toda esta fuente?» con
   flags reales por etapa, contadores de unidades y coverage_ratio ponderado.
   ``pipeline_complete`` habilita la reanudación selectiva (misma fuente +
   misma versión de pipeline = SKIP).
2. ``knowledge_semantic_windows``: plan de ventanas semánticas soft por
   documento (unidad_start/end sobre el orden de lectura, tokens, límites,
   estado). Es el checkpoint por ventana de las fases siguientes.

Aditiva: no toca tablas existentes.

Revision ID: 143
Revises: 141
"""
from __future__ import annotations

from alembic import op

revision: str = "143"
down_revision: str = "141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_ingestion_manifests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            external_id VARCHAR(512) NOT NULL,
            source_type VARCHAR(40) NOT NULL DEFAULT '',
            raw_fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            content_hash VARCHAR(64) NOT NULL DEFAULT '',
            total_bytes BIGINT NOT NULL DEFAULT 0,
            estimated_tokens BIGINT NOT NULL DEFAULT 0,
            structural_units INTEGER NOT NULL DEFAULT 0,
            processed_units INTEGER NOT NULL DEFAULT 0,
            semantic_units INTEGER NOT NULL DEFAULT 0,
            unresolved_units INTEGER NOT NULL DEFAULT 0,
            failed_units INTEGER NOT NULL DEFAULT 0,
            windows_total INTEGER NOT NULL DEFAULT 0,
            windows_processed INTEGER NOT NULL DEFAULT 0,
            parsing_complete BOOLEAN NOT NULL DEFAULT false,
            semantic_complete BOOLEAN NOT NULL DEFAULT false,
            stitching_complete BOOLEAN NOT NULL DEFAULT false,
            global_synthesis_complete BOOLEAN NOT NULL DEFAULT false,
            indexing_complete BOOLEAN NOT NULL DEFAULT false,
            pipeline_complete BOOLEAN NOT NULL DEFAULT false,
            coverage_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
            stages JSONB NOT NULL DEFAULT '{}',
            versions JSONB NOT NULL DEFAULT '{}',
            details JSONB NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ,
            UNIQUE (organization_id, source_id, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_manifests_org_source "
        "ON knowledge_ingestion_manifests(organization_id, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_manifests_org_updated "
        "ON knowledge_ingestion_manifests(organization_id, updated_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_windows (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            window_index INTEGER NOT NULL,
            unit_start INTEGER NOT NULL DEFAULT 0,
            unit_end INTEGER NOT NULL DEFAULT 0,
            first_block_id UUID,
            last_block_id UUID,
            estimated_tokens INTEGER NOT NULL DEFAULT 0,
            target_tokens INTEGER NOT NULL DEFAULT 0,
            hard_limit_tokens INTEGER NOT NULL DEFAULT 0,
            preserved_units INTEGER NOT NULL DEFAULT 0,
            split_units INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'planned',
            fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            plan_version VARCHAR(60) NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, window_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_windows_org_document "
        "ON knowledge_semantic_windows(organization_id, document_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_windows")
    op.execute("DROP TABLE IF EXISTS knowledge_ingestion_manifests")

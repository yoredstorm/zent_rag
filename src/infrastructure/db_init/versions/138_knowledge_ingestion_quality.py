"""Knowledge OS — cola de calidad de ingesta (INGESTION_QUALITY_QUEUE).

Separa explícitamente dos problemas que antes se mezclaban:

1. ``knowledge_ingestion_quality``: problemas de PARSING / EXTRACCIÓN
   (fragmentos, cortes de layout, fuente o evidencia ausente, candidatos de
   baja calidad). No son conocimiento contradictorio: son calidad de ingesta.

2. ``knowledge_conflicts`` sigue siendo exclusivamente para conflictos
   semánticos que pasaron el gate estricto (evidencia y fuentes en ambos
   lados). Los candidatos auto-resueltos ya no se muestran como conflictos.

Revision ID: 138
Revises: 137
"""
from __future__ import annotations

from alembic import op

revision: str = "138"
down_revision: str = "137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_ingestion_quality (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            kind VARCHAR(80) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'medium'
                CHECK (severity IN ('low','medium','high')),
            subject VARCHAR(512) NOT NULL DEFAULT '',
            detail JSONB NOT NULL DEFAULT '{}',
            evidence_locator VARCHAR(1000),
            evidence_excerpt TEXT,
            locator VARCHAR(1000),
            status VARCHAR(24) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','ignored','resolved')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_quality_org_status "
        "ON knowledge_ingestion_quality(organization_id, status, severity)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_quality_document "
        "ON knowledge_ingestion_quality(organization_id, document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_ingestion_quality_kind "
        "ON knowledge_ingestion_quality(organization_id, kind)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_ingestion_quality")

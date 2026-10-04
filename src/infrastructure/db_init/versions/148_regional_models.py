"""Progressive Semantic Ingestion — modelos regionales (Fase 6).

``knowledge_regional_models``: una fila por región lógica de un documento
(capítulo/sección de primer nivel; "document" para preámbulo sin sección).
Consolida definiciones, reglas, conceptos, entidades, excepciones,
procedimientos, condiciones, símbolos, claims, tablas, conflictos,
relaciones y dependencias sin resolver, con fingerprint determinista.

La escritura es un replace por documento (idempotente por corrida de stitch).

Revision ID: 148
Revises: 147
"""
from __future__ import annotations

from alembic import op

revision: str = "148"
down_revision: str = "147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_regional_models (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            region_id VARCHAR(300) NOT NULL,
            label VARCHAR(300) NOT NULL DEFAULT '',
            window_start INTEGER NOT NULL DEFAULT 0,
            window_end INTEGER NOT NULL DEFAULT 0,
            window_indexes JSONB NOT NULL DEFAULT '[]',
            model JSONB NOT NULL DEFAULT '{}',
            stats JSONB NOT NULL DEFAULT '{}',
            fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, region_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_regions_org_doc "
        "ON knowledge_regional_models(organization_id, document_id, window_start)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_regional_models")

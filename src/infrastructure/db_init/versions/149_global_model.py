"""Progressive Semantic Ingestion — modelo global (Fase 7).

``knowledge_global_models``: una fila por documento con la síntesis global
estructurada (glossary, concepts, entities, rules, dependencies, symbols,
exceptions, unresolved, temporal model, reference graph, semantic clusters),
fingerprint determinista y stats.

MAP (ventanas) -> REDUCE (regiones) -> RECONCILE (links) -> GLOBAL.

Revision ID: 149
Revises: 148
"""
from __future__ import annotations

from alembic import op

revision: str = "149"
down_revision: str = "148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_global_models (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            model JSONB NOT NULL DEFAULT '{}',
            stats JSONB NOT NULL DEFAULT '{}',
            fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_global_org_doc "
        "ON knowledge_global_models(organization_id, document_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_global_models")

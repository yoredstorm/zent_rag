"""Progressive Semantic Ingestion — unidades y relaciones del stitcher (Fase 5).

Dos tablas del SemanticStitcher:

1. ``knowledge_semantic_units``: unidades semánticas merged de todo el
   documento (misma clave en N ventanas = una unidad) con provenance a
   block_ids y ventanas.
2. ``knowledge_semantic_relations``: relaciones tipadas entre unidades
   (DEFINES/USES/HAS_EXCEPTION/REFERENCES/ALIAS_OF/CONTRADICTS/SUPERSEDES/
   SAME_AS/HAS_ATTRIBUTE/HAS_CONDITION/PART_OF) con evidencia física.

La escritura es un replace por documento (idempotente por corrida de stitch).

Revision ID: 147
Revises: 146
"""
from __future__ import annotations

from alembic import op

revision: str = "147"
down_revision: str = "146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_units (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            unit_key VARCHAR(300) NOT NULL,
            unit_kind VARCHAR(40) NOT NULL,
            label VARCHAR(300) NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            source_windows JSONB NOT NULL DEFAULT '[]',
            block_ids JSONB NOT NULL DEFAULT '[]',
            merged_from JSONB NOT NULL DEFAULT '[]',
            attributes JSONB NOT NULL DEFAULT '{}',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, unit_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_units_org_doc_kind "
        "ON knowledge_semantic_units(organization_id, document_id, unit_kind)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_relations (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            relation_key VARCHAR(700) NOT NULL,
            relation_type VARCHAR(40) NOT NULL,
            subject_key VARCHAR(300) NOT NULL,
            subject_kind VARCHAR(40) NOT NULL,
            subject_label VARCHAR(300) NOT NULL DEFAULT '',
            object_key VARCHAR(300) NOT NULL,
            object_kind VARCHAR(40) NOT NULL,
            object_label VARCHAR(300) NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            method VARCHAR(40) NOT NULL DEFAULT 'deterministic',
            evidence JSONB NOT NULL DEFAULT '[]',
            windows JSONB NOT NULL DEFAULT '[]',
            attributes JSONB NOT NULL DEFAULT '{}',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, relation_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_relations_org_doc_type "
        "ON knowledge_semantic_relations(organization_id, document_id, relation_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_relations")
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_units")

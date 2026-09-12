"""Knowledge V2 — Structured documents (Phase B).

Crea structured_documents + structured_blocks: la representación canónica del
árbol StructuredDocument (pages / sections / tables / figures / blocks) con el
mismo aislamiento (organization_id estricto + workspace/source) que el resto
de la plataforma. V1 (Markdown → chunks) no cambia; esta tabla es escritura
paralela solo cuando RAG_KNOWLEDGE_V2_ENABLED está activo.

Revision ID: 098
Revises: 097
"""
from __future__ import annotations

from alembic import op

revision: str = "098"
down_revision: str = "097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS structured_documents (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID NOT NULL,
            knowledge_base_id UUID,
            external_id VARCHAR(512) NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content_hash VARCHAR(64) NOT NULL,
            mime_type VARCHAR(120),
            document_type VARCHAR(64),
            language VARCHAR(16),
            provenance VARCHAR(16) NOT NULL DEFAULT 'OBSERVED',
            status VARCHAR(16) NOT NULL DEFAULT 'observed',
            page_count INTEGER NOT NULL DEFAULT 0,
            section_count INTEGER NOT NULL DEFAULT 0,
            table_count INTEGER NOT NULL DEFAULT 0,
            figure_count INTEGER NOT NULL DEFAULT 0,
            block_count INTEGER NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, source_id, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_documents_org_source "
        "ON structured_documents(organization_id, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_documents_org_updated "
        "ON structured_documents(organization_id, updated_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS structured_blocks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL
                REFERENCES structured_documents(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            node_type VARCHAR(16) NOT NULL
                CHECK (node_type IN ('block','page','section','table','figure')),
            kind VARCHAR(32) NOT NULL DEFAULT 'paragraph',
            content_type VARCHAR(24) NOT NULL DEFAULT 'text',
            text TEXT NOT NULL DEFAULT '',
            order_index INTEGER NOT NULL DEFAULT 0,
            page_number INTEGER,
            section_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            parent_id UUID,
            depth INTEGER,
            heading TEXT,
            page_start INTEGER,
            page_end INTEGER,
            char_start INTEGER,
            char_end INTEGER,
            bbox JSONB,
            language VARCHAR(16),
            token_count INTEGER NOT NULL DEFAULT 0,
            content_hash VARCHAR(64),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_blocks_document "
        "ON structured_blocks(document_id, order_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_blocks_org_source "
        "ON structured_blocks(organization_id, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_blocks_org_page "
        "ON structured_blocks(organization_id, page_number)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS structured_blocks")
    op.execute("DROP TABLE IF EXISTS structured_documents")

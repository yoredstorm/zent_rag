"""Knowledge V2 — KnowledgeCorpus persistence (Phase D slice 2).

Cuartel general del modelo de corpus: un corpus es workspace-scoped y
org-scoped (ADR §2.1) y agrupa sources consultables. kb_sources/knowledge_bases
ganan corpus_id nullable (overlay; no rompe V1). Head: 098.

Revision ID: 099
Revises: 098
"""
from __future__ import annotations

from alembic import op

revision: str = "099"
down_revision: str = "098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_corpora (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            slug VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            knowledge_base_id UUID,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, workspace_id, slug)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_corpora_org_workspace "
        "ON knowledge_corpora(organization_id, workspace_id)"
    )

    op.execute(
        "ALTER TABLE kb_sources ADD COLUMN IF NOT EXISTS corpus_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_kb_sources_knowledge_corpus'
            ) THEN
                ALTER TABLE kb_sources ADD CONSTRAINT fk_kb_sources_knowledge_corpus
                    FOREIGN KEY (corpus_id) REFERENCES knowledge_corpora(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_sources_corpus "
        "ON kb_sources(organization_id, corpus_id)"
    )

    op.execute(
        "ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS corpus_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_knowledge_bases_knowledge_corpus'
            ) THEN
                ALTER TABLE knowledge_bases ADD CONSTRAINT fk_knowledge_bases_knowledge_corpus
                    FOREIGN KEY (corpus_id) REFERENCES knowledge_corpora(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_bases_corpus "
        "ON knowledge_bases(organization_id, corpus_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_bases DROP CONSTRAINT IF EXISTS fk_knowledge_bases_knowledge_corpus")
    op.execute("ALTER TABLE knowledge_bases DROP COLUMN IF EXISTS corpus_id")
    op.execute("ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS fk_kb_sources_knowledge_corpus")
    op.execute("ALTER TABLE kb_sources DROP COLUMN IF EXISTS corpus_id")
    op.execute("DROP TABLE IF EXISTS knowledge_corpora")

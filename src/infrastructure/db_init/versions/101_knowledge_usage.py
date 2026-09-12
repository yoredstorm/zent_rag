"""Knowledge V2 — usage & cost registry (brief §41).

knowledge_usage registra costos por corpus/source/categoría (embedding, llm,
rerank, storage, query) con tokens + costo estimado. Aislamiento estricto por
organization_id + workspace. Head: 100.

Revision ID: 101
Revises: 100
"""
from __future__ import annotations

from alembic import op

revision: str = "101"
down_revision: str = "100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_usage (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            corpus_id UUID,
            source_id UUID,
            category VARCHAR(16) NOT NULL
                CHECK (category IN ('embedding','llm','rerank','storage','query')),
            tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_usage_org_window "
        "ON knowledge_usage(organization_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_usage_org_corpus "
        "ON knowledge_usage(organization_id, corpus_id, category)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_usage")

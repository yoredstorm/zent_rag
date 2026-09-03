"""AI Knowledge Hub v2 — Auto-Discovery & Curation.

Revision ID: 065
Revises: 064
Create Date: 2026-09-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "065"
down_revision: Union[str, None] = "064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(150) NOT NULL,
            source_type VARCHAR(20) NOT NULL DEFAULT 'url',
            config JSONB NOT NULL DEFAULT '{}',
            refresh_interval_h INT NOT NULL DEFAULT 24,
            last_refresh_at TIMESTAMPTZ,
            next_refresh_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_sources_org "
        "ON knowledge_sources(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_refreshes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_id UUID NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            docs_found INT NOT NULL DEFAULT 0,
            docs_added INT NOT NULL DEFAULT 0,
            docs_duplicated INT NOT NULL DEFAULT 0,
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            duration_ms INT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_refreshes_source "
        "ON knowledge_refreshes(source_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_gaps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            query VARCHAR(300) NOT NULL,
            intent VARCHAR(30),
            occurrences INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, query)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_org "
        "ON knowledge_gaps(organization_id, status, occurrences DESC)"
    )
    # Enriquecer documents con metadatos de curación y deduplicación.
    op.execute(
        "ALTER TABLE documents "
        "ADD COLUMN IF NOT EXISTS source_id UUID, "
        "ADD COLUMN IF NOT EXISTS category VARCHAR(60), "
        "ADD COLUMN IF NOT EXISTS author VARCHAR(120), "
        "ADD COLUMN IF NOT EXISTS freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0, "
        "ADD COLUMN IF NOT EXISTS signature VARCHAR(64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_signature "
        "ON documents(organization_id, signature)"
    )


def downgrade() -> None:
    for table in ("knowledge_refreshes", "knowledge_gaps", "knowledge_sources"):
        op.execute(f"DROP TABLE IF EXISTS {table}")

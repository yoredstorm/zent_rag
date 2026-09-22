"""Replay runs, separate from the original rag_flows row.

Revision ID: 128
Revises: 127
"""
from __future__ import annotations

from alembic import op

revision: str = "128"
down_revision: str = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS query_replays (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_query_id UUID NOT NULL,
            replay_query_id UUID NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_query_replays_org_source
        ON query_replays (organization_id, source_query_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS query_replays")

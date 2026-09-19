"""Flujo completo por respuesta — tabla chica para "Ver flujo" en el chat.

Revision ID: 123
Revises: 122
"""

from __future__ import annotations

from alembic import op

revision: str = "123"
down_revision: str = "122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rag_flows (
            query_id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            conversation_id UUID,
            request_id UUID,
            user_id UUID,
            method VARCHAR(20) NOT NULL DEFAULT 'rag',
            status VARCHAR(30) NOT NULL DEFAULT 'completed',
            flow JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_rag_flows_org_time
        ON rag_flows (organization_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rag_flows")

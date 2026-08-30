"""Agent embed tokens for public chat widgets.

Revision ID: 017
Revises: 016
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_embed_tokens (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            public_id VARCHAR(64) NOT NULL UNIQUE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            token_prefix VARCHAR(20) NOT NULL,
            allowed_origins TEXT[] NOT NULL DEFAULT '{}',
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embed_tokens_agent ON agent_embed_tokens(agent_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embed_tokens_public ON agent_embed_tokens(public_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_embed_tokens")

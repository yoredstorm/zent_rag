"""AI Agent Versioning & Rollout v2 — agent_releases y release_events.

Revision ID: 061
Revises: 060
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "061"
down_revision: Union[str, None] = "060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_releases (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id UUID NOT NULL,
            version_id UUID NOT NULL,
            channel VARCHAR(20) NOT NULL DEFAULT 'canary',
            traffic_pct INT NOT NULL DEFAULT 100,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            health_score DOUBLE PRECISION,
            promoted_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            promoted_at TIMESTAMPTZ,
            rolled_back_at TIMESTAMPTZ,
            notes TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_releases_agent "
        "ON agent_releases(agent_id, channel, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS release_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            release_id UUID NOT NULL,
            event_type VARCHAR(30) NOT NULL,
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_release_events_release "
        "ON release_events(release_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS release_events")
    op.execute("DROP TABLE IF EXISTS agent_releases")

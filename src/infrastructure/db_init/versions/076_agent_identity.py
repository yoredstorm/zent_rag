"""FASE 03 — Agent identity (created_by) + delegated permissions.

Revision ID: 076
Revises: 075
"""
from __future__ import annotations

from alembic import op

revision: str = "076"
down_revision: str = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_permissions (
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            permission VARCHAR(60) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (agent_id, permission)
        )
        """
    )
    # Backfill: creador desde el audit agent.created (best-effort).
    op.execute(
        """
        UPDATE agents a SET created_by = (
            SELECT al.actor_user_id FROM audit_logs al
            WHERE al.action = 'agent.created' AND al.resource_id = a.id::text
            ORDER BY al.created_at LIMIT 1
        )
        WHERE a.created_by IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_permissions")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS created_by")

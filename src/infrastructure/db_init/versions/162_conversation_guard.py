"""conversation guard state

Revision ID: 162
Revises: 161
"""
from __future__ import annotations

from alembic import op

revision: str = "162"
down_revision: str = "161"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_conversation_guards (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            scope_type VARCHAR(20) NOT NULL,
            scope_key VARCHAR(64) NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0,
            warning_sent BOOLEAN NOT NULL DEFAULT FALSE,
            cooldown_until TIMESTAMPTZ,
            last_failure_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, scope_type, scope_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_conversation_guards_scope
        ON workflow_conversation_guards(organization_id, scope_type, scope_key)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_conversation_guards")

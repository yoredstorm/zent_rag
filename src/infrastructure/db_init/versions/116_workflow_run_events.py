"""Workflow run events — timeline append-only para el Execution Inspector (D6).

Revision ID: 116
Revises: 115
"""
from __future__ import annotations

from alembic import op

revision: str = "116"
down_revision: str = "115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            seq BIGSERIAL,
            kind VARCHAR(40) NOT NULL,
            node_id VARCHAR(80),
            payload JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_run_events_run "
        "ON workflow_run_events(run_id, seq)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_run_events_org "
        "ON workflow_run_events(organization_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_run_events_org")
    op.execute("DROP INDEX IF EXISTS idx_wf_run_events_run")
    op.execute("DROP TABLE IF EXISTS workflow_run_events")

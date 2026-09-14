"""Workflow Studio UX v2 — ejecución parcial (run_mode/target/source) + pinned test data.

Revision ID: 112
Revises: 111
"""
from __future__ import annotations

from alembic import op

revision: str = "112"
down_revision: str = "111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS run_mode VARCHAR(20) NOT NULL DEFAULT 'full', "
        "ADD COLUMN IF NOT EXISTS target_node_id VARCHAR(80), "
        "ADD COLUMN IF NOT EXISTS source_run_id UUID"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_pinned_data (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workflow_id UUID NOT NULL,
            node_id VARCHAR(80) NOT NULL,
            output JSONB NOT NULL DEFAULT '{}',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workflow_id, node_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_pinned_org "
        "ON workflow_pinned_data(organization_id, workflow_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_pinned_data")
    op.execute(
        "ALTER TABLE workflow_runs DROP COLUMN IF EXISTS run_mode, "
        "DROP COLUMN IF EXISTS target_node_id, "
        "DROP COLUMN IF EXISTS source_run_id"
    )

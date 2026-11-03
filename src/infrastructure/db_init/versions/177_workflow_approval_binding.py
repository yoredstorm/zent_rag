"""P18.5 — vínculo verificable de aprobaciones con la operación.

Revision ID: 177
Revises: 176
"""
from __future__ import annotations

from alembic import op

revision: str = "177"
down_revision: str = "176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS instance_id UUID"
    )
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS workflow_version INTEGER"
    )
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS graph_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS capability_ref VARCHAR(160)"
    )
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS target_node_id VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS approval_scope JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_approvals_instance "
        "ON workflow_approvals(organization_id, instance_id, status)"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS workflow_approval_consumptions ("
        " id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        " approval_id UUID NOT NULL,"
        " organization_id UUID NOT NULL,"
        " run_id UUID NOT NULL,"
        " node_id VARCHAR(120) NOT NULL,"
        " operation_id VARCHAR(200),"
        " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
        " UNIQUE (approval_id, run_id, node_id)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_approval_consumptions_org "
        "ON workflow_approval_consumptions(organization_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_approval_consumptions")
    for column in (
        "approval_scope",
        "target_node_id",
        "capability_ref",
        "graph_hash",
        "workflow_version",
        "instance_id",
    ):
        op.execute(f"ALTER TABLE workflow_approvals DROP COLUMN IF EXISTS {column}")

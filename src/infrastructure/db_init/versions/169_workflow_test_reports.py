"""Persisted Workflow Test Studio reports.

Revision ID: 169
Revises: 168

The report is evidence, not a second certification store. It records the
server-decided level and the hashes that make a later stale check possible.
"""
from __future__ import annotations

from alembic import op

revision: str = "169"
down_revision: str = "168"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_test_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            workflow_id UUID NOT NULL,
            requested_level VARCHAR(20) NOT NULL,
            effective_level VARCHAR(20) NOT NULL,
            result VARCHAR(24) NOT NULL,
            graph_hash VARCHAR(64) NOT NULL DEFAULT '',
            plan_hash VARCHAR(64) NOT NULL DEFAULT '',
            role_hash VARCHAR(64) NOT NULL DEFAULT '',
            binding_hash VARCHAR(64) NOT NULL DEFAULT '',
            scenario JSONB NOT NULL DEFAULT '{}'::jsonb,
            report JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_test_reports_scope
        ON workflow_test_reports (organization_id, workflow_id, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_test_reports_scope")
    op.execute("DROP TABLE IF EXISTS workflow_test_reports")

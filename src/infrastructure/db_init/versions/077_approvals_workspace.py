"""FASE 03 — Human-in-the-loop approvals + workspace tasks/activity.

Revision ID: 077
Revises: 076
"""
from __future__ import annotations

from alembic import op

revision: str = "077"
down_revision: str = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            run_id UUID,
            tool VARCHAR(60) NOT NULL,
            summary TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'approved', 'rejected', 'used')),
            decided_by UUID,
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_approvals_org_status "
        "ON approval_requests(organization_id, status, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_tasks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            title VARCHAR(300) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'todo'
                CHECK (status IN ('todo', 'in_progress', 'done')),
            assignee_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_activity (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            event_type VARCHAR(40) NOT NULL,
            detail TEXT,
            actor_user_id UUID,
            agent_id UUID REFERENCES agents(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_activity "
        "ON workspace_activity(workspace_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approval_requests")
    op.execute("DROP TABLE IF EXISTS workspace_tasks")
    op.execute("DROP TABLE IF EXISTS workspace_activity")

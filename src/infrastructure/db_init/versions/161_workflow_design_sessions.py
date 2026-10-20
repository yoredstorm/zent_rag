"""workflow design sessions

Revision ID: 161
Revises: 160
"""
from __future__ import annotations

from alembic import op

revision: str = "161"
down_revision: str = "160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_design_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            user_id UUID,
            title VARCHAR(200) NOT NULL DEFAULT 'Diseño',
            original_prompt TEXT NOT NULL DEFAULT '',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            revision INT NOT NULL DEFAULT 0,
            plan JSONB,
            graph JSONB,
            plan_hash VARCHAR(64),
            capability_snapshot_hash VARCHAR(64),
            workflow_id UUID,
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_design_sessions_org
        ON workflow_design_sessions(organization_id, workspace_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_design_revisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES workflow_design_sessions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            revision INT NOT NULL,
            user_id UUID,
            kind VARCHAR(30) NOT NULL DEFAULT 'patch',
            instruction TEXT,
            summary TEXT,
            diff JSONB NOT NULL DEFAULT '{}'::jsonb,
            plan JSONB,
            graph JSONB,
            plan_hash VARCHAR(64),
            validation JSONB NOT NULL DEFAULT '{}'::jsonb,
            simulation JSONB NOT NULL DEFAULT '{}'::jsonb,
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (session_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_design_revisions_session
        ON workflow_design_revisions(session_id, revision DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_design_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id UUID NOT NULL REFERENCES workflow_design_sessions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            user_id UUID,
            revision INT NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_design_messages_session
        ON workflow_design_messages(session_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_design_messages")
    op.execute("DROP TABLE IF EXISTS workflow_design_revisions")
    op.execute("DROP TABLE IF EXISTS workflow_design_sessions")

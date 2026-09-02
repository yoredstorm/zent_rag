"""Workflows & Automation — definiciones, runs y pasos.

Revision ID: 038
Revises: 037
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            enabled BOOLEAN NOT NULL DEFAULT true,
            trigger_type VARCHAR(20) NOT NULL DEFAULT 'manual',
            cron_expr VARCHAR(60),
            steps JSONB NOT NULL DEFAULT '[]',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_run_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_defs_org "
        "ON workflow_definitions(organization_id, enabled)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workflow_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            trigger VARCHAR(20) NOT NULL DEFAULT 'manual',
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            current_step INT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            error TEXT,
            created_by UUID
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_runs_org "
        "ON workflow_runs(organization_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            step_index INT NOT NULL,
            step_type VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            details JSONB NOT NULL DEFAULT '{}',
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            UNIQUE (run_id, step_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_steps_run "
        "ON workflow_run_steps(run_id, step_index)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_workflow_steps_run")
    op.execute("DROP TABLE IF EXISTS workflow_run_steps")
    op.execute("DROP INDEX IF EXISTS idx_workflow_runs_org")
    op.execute("DROP TABLE IF EXISTS workflow_runs")
    op.execute("DROP INDEX IF EXISTS idx_workflow_defs_org")
    op.execute("DROP TABLE IF EXISTS workflow_definitions")

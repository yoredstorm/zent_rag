"""PHASE 31C — Managed databases + schema proposals.

Revision ID: 086
Revises: 085
"""
from __future__ import annotations

from alembic import op

revision: str = "086"
down_revision: str = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS managed_databases (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            provider VARCHAR(40) NOT NULL DEFAULT 'local',
            db_name VARCHAR(120) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ready',
            size_quota_mb INT NOT NULL DEFAULT 256,
            connector_id UUID,
            backup_retention_days INT NOT NULL DEFAULT 0,
            last_backup_at TIMESTAMPTZ,
            restore_ready BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS managed_schema_proposals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID NOT NULL,
            managed_database_id UUID NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
            prompt TEXT,
            proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            ddl_preview TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS managed_schema_proposals")
    op.execute("DROP TABLE IF EXISTS managed_databases")

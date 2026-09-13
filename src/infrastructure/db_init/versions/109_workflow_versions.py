"""Workflow Studio — versiones publicables del workflow (snapshot + rollback).

Una fila de `workflow_versions` congela lo publicable de un workflow (nombre,
trigger, steps, grafo). El hook y /run siguen ejecutando la fila viva; restaurar
una versión reescribe esa fila. El secret del webhook no entra al snapshot.

Revision ID: 109
Revises: 108
"""
from __future__ import annotations

from alembic import op

revision: str = "109"
down_revision: str = "108"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'ready', 'production', 'archived')),
            config_snapshot JSONB NOT NULL DEFAULT '{}',
            notes TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (workflow_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_versions_wf "
        "ON workflow_versions(workflow_id, version_number DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_versions_org "
        "ON workflow_versions(organization_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_versions")

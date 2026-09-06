"""FASE 03 — Quality Gates configurables por organización/workspace.

Revision ID: 075
Revises: 074
"""
from __future__ import annotations

from alembic import op

revision: str = "075"
down_revision: str = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quality_gates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE,
            thresholds JSONB NOT NULL DEFAULT '{}',
            max_hallucination DOUBLE PRECISION,
            max_regression_pct DOUBLE PRECISION NOT NULL DEFAULT 5,
            updated_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, workspace_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS quality_gates")

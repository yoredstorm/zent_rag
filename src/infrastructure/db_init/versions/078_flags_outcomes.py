"""FASE 03 — Feature flags + business outcomes.

Revision ID: 078
Revises: 077
"""
from __future__ import annotations

from alembic import op

revision: str = "078"
down_revision: str = "077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS feature_flags (
            key VARCHAR(80) NOT NULL,
            scope VARCHAR(20) NOT NULL DEFAULT 'platform'
                CHECK (scope IN ('platform', 'plan', 'organization', 'workspace')),
            plan_name VARCHAR(50),
            organization_id UUID,
            workspace_id UUID,
            enabled BOOLEAN NOT NULL DEFAULT false,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (key, scope, plan_name, organization_id, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_metrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id UUID REFERENCES agents(id) ON DELETE CASCADE,
            metric_key VARCHAR(80) NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            period_start DATE,
            period_end DATE,
            source VARCHAR(60),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_metrics_agent "
        "ON business_metrics(organization_id, agent_id, metric_key, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature_flags")
    op.execute("DROP TABLE IF EXISTS business_metrics")

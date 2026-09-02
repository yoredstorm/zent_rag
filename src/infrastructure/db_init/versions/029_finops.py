"""FinOps — deployment_id en usage_events + finops_alerts + budget por org.

Revision ID: 029
Revises: 028
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS deployment_id UUID "
        "REFERENCES deployments(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_deployment "
        "ON usage_events(deployment_id)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS "
        "finops_budget_cents BIGINT"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS finops_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            alert_type VARCHAR(40) NOT NULL,
            message TEXT NOT NULL,
            threshold_value DOUBLE PRECISION,
            actual_value DOUBLE PRECISION,
            acknowledged BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_finops_alerts_org "
        "ON finops_alerts(organization_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS finops_alerts")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS finops_budget_cents")
    op.execute("DROP INDEX IF EXISTS idx_usage_events_deployment")
    op.execute("ALTER TABLE usage_events DROP COLUMN IF EXISTS deployment_id")

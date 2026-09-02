"""Cost Governance & FinOps v2 — cost_tags, usage_events.cost_tags,
cost_alert_rules/alerts, org cost_team/business_unit.

Revision ID: 048
Revises: 047
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "048"
down_revision: Union[str, None] = "047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_tags (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            key VARCHAR(60) NOT NULL,
            value VARCHAR(120) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, key, value)
        )
        """
    )
    op.execute(
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS cost_tags JSONB NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_cost_tags "
        "ON usage_events USING GIN (cost_tags)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_alert_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            category VARCHAR(40) NOT NULL DEFAULT 'total',
            dimension VARCHAR(120),
            threshold_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
            adaptive BOOLEAN NOT NULL DEFAULT true,
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cost_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            rule_id UUID,
            category VARCHAR(40) NOT NULL DEFAULT 'total',
            dimension VARCHAR(120),
            baseline_daily_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
            today_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
            threshold_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
            triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (rule_id, triggered_at)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_cost_alerts_org_time ON cost_alerts(organization_id, triggered_at DESC)")
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cost_team VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cost_business_unit VARCHAR(120)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS cost_business_unit")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS cost_team")
    op.execute("DROP TABLE IF EXISTS cost_alerts")
    op.execute("DROP TABLE IF EXISTS cost_alert_rules")
    op.execute("ALTER TABLE usage_events DROP COLUMN IF EXISTS cost_tags")
    op.execute("DROP TABLE IF EXISTS cost_tags")

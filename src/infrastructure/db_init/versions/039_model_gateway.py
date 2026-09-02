"""Model Gateway — model_routes (A/B, condiciones) + model_budgets + routing.

Revision ID: 039
Revises: 038
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_routes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(120) NOT NULL,
            condition_type VARCHAR(20) NOT NULL DEFAULT 'default',
            condition_value DOUBLE PRECISION,
            model VARCHAR(120) NOT NULL,
            traffic_pct INT NOT NULL DEFAULT 100,
            priority INT NOT NULL DEFAULT 0,
            active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_routes_org "
        "ON model_routes(organization_id, active, priority)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_budgets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            model VARCHAR(120) NOT NULL,
            monthly_budget_cents INT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, model)
        )
        """
    )
    op.execute(
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS routing JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE usage_events DROP COLUMN IF EXISTS routing")
    op.execute("DROP TABLE IF EXISTS model_budgets")
    op.execute("DROP INDEX IF EXISTS idx_model_routes_org")
    op.execute("DROP TABLE IF EXISTS model_routes")

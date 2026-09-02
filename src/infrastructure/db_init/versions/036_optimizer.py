"""Optimizer — optimizer_actions (recomendaciones de costo/desempeño).

Revision ID: 036
Revises: 035
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS optimizer_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            agent_id UUID,
            deployment_id UUID,
            recommendation_key VARCHAR(60) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            expected_savings_pct DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'suggested',
            details JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            applied_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_optimizer_org "
        "ON optimizer_actions(organization_id, status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_optimizer_org")
    op.execute("DROP TABLE IF EXISTS optimizer_actions")

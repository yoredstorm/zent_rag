"""Plan provider prices (Stripe Price IDs per plan/interval).

Revision ID: 016
Revises: 015
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_provider_prices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            interval VARCHAR(10) NOT NULL CHECK (interval IN ('monthly', 'annual')),
            provider VARCHAR(30) NOT NULL,
            price_id VARCHAR(200) NOT NULL,
            UNIQUE (plan_id, interval, provider)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS plan_provider_prices")

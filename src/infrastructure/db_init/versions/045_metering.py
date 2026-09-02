"""Metering v2 — rate_limit_rules por plan con burst.

Revision ID: 045
Revises: 044
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "045"
down_revision: Union[str, None] = "044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_name VARCHAR(50),
            endpoint_prefix VARCHAR(120) NOT NULL DEFAULT '/',
            limit_per_minute INT NOT NULL DEFAULT 30,
            burst INT NOT NULL DEFAULT 10,
            enabled BOOLEAN NOT NULL DEFAULT true,
            priority INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO rate_limit_rules (plan_name, endpoint_prefix, limit_per_minute, burst, priority) VALUES
        ('trial', '/', 30, 10, 10),
        ('starter', '/', 60, 15, 10),
        ('pro', '/', 100, 25, 10),
        ('enterprise', '/', 500, 100, 10),
        (NULL, '/api/v1/rag/query', 60, 15, 20),
        (NULL, '/api/v1/deployments', 200, 50, 20)
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limit_rules")

"""Capacity Planning — scaling_events.

Revision ID: 041
Revises: 040
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scaling_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            queue VARCHAR(60) NOT NULL,
            action VARCHAR(20) NOT NULL,
            worker_count_target INT,
            depth INT,
            reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_scaling_events_created "
        "ON scaling_events(created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_scaling_events_created")
    op.execute("DROP TABLE IF EXISTS scaling_events")

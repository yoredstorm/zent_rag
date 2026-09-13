"""Integration Experience — manifest v2 (events column).

Revision ID: 111
Revises: 110
"""
from __future__ import annotations

from alembic import op

revision: str = "111"
down_revision: str = "110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE integration_manifests ADD COLUMN IF NOT EXISTS events "
        "JSONB NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE integration_manifests DROP COLUMN IF EXISTS events")

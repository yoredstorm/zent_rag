"""Control Center inbox (platform_notifications).

Revision ID: 020
Revises: 019
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            type VARCHAR(80) NOT NULL,
            organization_id UUID,
            title VARCHAR(240) NOT NULL,
            body TEXT,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            read_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_platform_notifications_unread "
        "ON platform_notifications (created_at DESC) WHERE read_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_platform_notifications_unread")
    op.execute("DROP TABLE IF EXISTS platform_notifications")

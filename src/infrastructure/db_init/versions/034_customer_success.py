"""Customer Success — onboarding, branding, report subscriptions, email flags.

Revision ID: 034
Revises: 033
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS onboarding_step INT "
        "NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS branding JSONB "
        "NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE organization_invites ADD COLUMN IF NOT EXISTS email_sent BOOLEAN "
        "NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE organization_invites ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_subscriptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            email VARCHAR(320) NOT NULL,
            frequency VARCHAR(20) NOT NULL DEFAULT 'monthly',
            next_send_at TIMESTAMPTZ NOT NULL,
            last_sent_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, email, frequency)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_subscriptions")
    op.execute("ALTER TABLE organization_invites DROP COLUMN IF EXISTS delivery_status")
    op.execute("ALTER TABLE organization_invites DROP COLUMN IF EXISTS email_sent")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS branding")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS onboarding_completed_at")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS onboarding_step")

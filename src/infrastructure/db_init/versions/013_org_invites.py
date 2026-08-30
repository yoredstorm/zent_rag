"""Organization invites — pending memberships without a mailer.

Revision ID: 013
Revises: 012
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_invites (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            email VARCHAR(320) NOT NULL,
            role VARCHAR(20) NOT NULL
                CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
            token_hash VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            accepted_at TIMESTAMPTZ,
            created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_invites_org_email "
        "ON organization_invites (organization_id, email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_org_invites_token_hash "
        "ON organization_invites (token_hash)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_invites")

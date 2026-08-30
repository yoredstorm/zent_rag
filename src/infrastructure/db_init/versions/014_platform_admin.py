"""Platform admin flag and nullable organization_id for Control Center users.

Revision ID: 014
Revises: 013
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "is_platform_admin BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE users ALTER COLUMN organization_id DROP NOT NULL")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
            CHECK (
                (is_platform_admin = true AND organization_id IS NULL)
                OR (is_platform_admin = false AND organization_id IS NOT NULL)
            )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_platform_admin "
        "ON users (is_platform_admin) WHERE is_platform_admin = true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk")
    op.execute("DROP INDEX IF EXISTS idx_users_platform_admin")
    op.execute(
        "DELETE FROM users WHERE organization_id IS NULL OR is_platform_admin = true"
    )
    op.execute("ALTER TABLE users ALTER COLUMN organization_id SET NOT NULL")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_platform_admin")

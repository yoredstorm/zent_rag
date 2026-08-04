"""Add portal auth columns (email, password_hash) to users.

Revision ID: 002
Revises: 001
Create Date: 2026-08-04

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(320)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
            ON users (lower(email))
            WHERE email IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users (lower(email))"
    )
    op.execute(
        """
        UPDATE users
        SET email = 'demo@zenttech.com'
        WHERE id = '00000000-0000-0000-0000-000000000002'
          AND email IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_email_unique")
    op.execute("DROP INDEX IF EXISTS idx_users_email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_hash")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")

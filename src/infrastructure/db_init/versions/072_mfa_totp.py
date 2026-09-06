"""MFA TOTP (FASE 07): tabla de enrollment para platform admins."""

from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mfa_totp (
            user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            secret_enc TEXT NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT false,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mfa_totp")

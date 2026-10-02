"""User access control — suspensión de usuarios desde el Control Center.

Añade ``users.disabled_at``: NULL = activo; timestamp = suspendido/desactivado.
El login (tenant y plataforma) bloquea a usuarios suspendidos, y la suspensión
revoca de inmediato todas sus sesiones (marcador por usuario en Redis), sin
tocar memberships ni la suscripción de la organización.

Revision ID: 137
Revises: 136
"""
from __future__ import annotations

from alembic import op

revision: str = "137"
down_revision: str = "136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_disabled "
        "ON users(disabled_at) WHERE disabled_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_disabled")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS disabled_at")

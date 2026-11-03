"""Retiro de las banderas de cliente.

Revision ID: 182
Revises: 181

Las superficies de cliente (signup, onboarding, equipo, facturación,
proyectos, espacios de trabajo) ya no existen como rutas: se eliminaron sus
páginas y sus chunks. La tabla `client_flags` queda sin uso.
"""
from __future__ import annotations

from alembic import op

revision: str = "187"
down_revision: str = "186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_flags")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_flags (
            key VARCHAR(80) PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

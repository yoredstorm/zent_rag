"""Pantalla «Aplicaciones» del Nivel 1 (catálogo general).

Revision ID: 179
Revises: 178

Aditiva. Registra la pantalla en el catálogo `screens` para que la matriz de
permisos por rol/usuario pueda asignarla.
"""
from __future__ import annotations

from alembic import op

revision: str = "184"
down_revision: str = "183"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO screens (code, name, category, path, sort_order) VALUES "
        "('applications', 'Aplicaciones', 'General', '/control-center/applications', 25) "
        "ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM screens WHERE code = 'applications'")

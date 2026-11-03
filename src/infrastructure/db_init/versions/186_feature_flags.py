"""Flags de runtime para las superficies de cliente.

Revision ID: 181
Revises: 180

Tabla propia (`client_flags`) en lugar de `feature_flags`: esa tabla tiene una
PK compuesta por (key, scope, plan_name, organization_id, workspace_id) con
columnas NOT NULL, así que no admite filas de alcance plataforma sin centinelas.

Siembra las banderas apagadas, según la recomendación del PDF §8:
ocultar → medir → eliminar.
"""
from __future__ import annotations

from alembic import op

revision: str = "186"
down_revision: str = "185"
branch_labels = None
depends_on = None

# Superficies de cliente: alta de cuentas, onboarding, equipo, facturación
# autoservicio, proyectos y espacios de trabajo.
_FLAGS = (
    "client.signup",
    "client.onboarding",
    "client.team",
    "client.billing",
    "client.projects",
    "client.workspaces",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_flags (
            key VARCHAR(80) PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT false,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    for key in _FLAGS:
        op.execute(
            "INSERT INTO client_flags (key, enabled) VALUES ('{key}', false) "
            "ON CONFLICT (key) DO NOTHING".format(key=key)
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_flags")

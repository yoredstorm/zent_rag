"""Model circuit breakers — aislamiento por tenant.

Revision ID: 151
Revises: 150
Create Date: 2026-10-11

La fila global (organization_id NULL) sigue siendo el breaker por modelo.
Cada tenant puede tener su propia fila: sus fallos abren SOLO su circuito,
sin tumbar al resto. Un provider caído para todos se detecta por métrica
(zent_model_circuit_openings_total con scope por org) y por el alert de
múltiples tenants abriendo el mismo modelo.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "151"
down_revision: Union[str, None] = "150"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE model_circuit_breakers "
        "ADD COLUMN IF NOT EXISTS organization_id UUID"
    )
    # El UNIQUE global del modelo pasa a ser UNIQUE por (modelo, scope).
    op.execute(
        "ALTER TABLE model_circuit_breakers "
        "DROP CONSTRAINT IF EXISTS model_circuit_breakers_model_name_key"
    )
    # COALESCE: en Postgres los NULL son distintos entre sí en un UNIQUE; el
    # sentinel UUID mantiene una única fila global por modelo.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_model_circuit_scope "
        "ON model_circuit_breakers "
        "(model_name, COALESCE(organization_id, "
        "'00000000-0000-0000-0000-000000000000'::uuid))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_model_circuit_org "
        "ON model_circuit_breakers (organization_id, model_name)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_model_circuit_org")
    op.execute("DROP INDEX IF EXISTS uq_model_circuit_scope")
    # Solo puede volver al esquema global si no hay circuitos por tenant.
    op.execute("DELETE FROM model_circuit_breakers WHERE organization_id IS NOT NULL")
    op.execute(
        "ALTER TABLE model_circuit_breakers DROP COLUMN IF EXISTS organization_id"
    )
    op.execute(
        "ALTER TABLE model_circuit_breakers "
        "ADD CONSTRAINT model_circuit_breakers_model_name_key UNIQUE (model_name)"
    )

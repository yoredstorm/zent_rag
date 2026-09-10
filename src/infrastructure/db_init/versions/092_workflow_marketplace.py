"""Phase 33B — Marketplace-native workflows: renderers por acción y costos por call.

Revision ID: 092
Revises: 091
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "092"
down_revision: str = "091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS renderer VARCHAR(120)")
    op.execute(
        "ALTER TABLE integration_actions ADD COLUMN IF NOT EXISTS "
        "provider VARCHAR(80) DEFAULT 'zent'"
    )

    # Renderers preferidos por acción (result cards reutilizables en el canvas).
    bind.execute(
        text(
            "UPDATE integration_actions SET renderer = :r WHERE action_id = :a"
        ),
        [
            {"a": "peru.taxpayer.lookup", "r": "taxpayer_verification"},
            {"a": "peru.identity.verify", "r": "identity_verification"},
            {"a": "currency.current_rate", "r": "fx_rate"},
            {"a": "demo.echo", "r": "plain"},
        ],
    )

    # Costos por call (S/): la UI los muestra como indicador y estimador de run.
    bind.execute(
        text(
            "UPDATE integration_actions SET cost_model = CAST(:cm AS jsonb) WHERE action_id = :a"
        ),
        [
            {"a": "peru.taxpayer.lookup", "cm": '{"model": "PER_CALL", "units": 1, "price": 0.02}'},
            {"a": "peru.identity.verify", "cm": '{"model": "PER_CALL", "units": 1, "price": 0.05}'},
        ],
    )
    # Default determinista para el resto de acciones pagadas sin precio explícito.
    bind.execute(
        text(
            "UPDATE integration_actions SET cost_model = jsonb_set(cost_model, '{price}', '0') "
            "WHERE cost_model->>'model' = 'PER_CALL' AND NOT cost_model ? 'price'"
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE integration_actions DROP COLUMN IF EXISTS renderer")
    op.execute("ALTER TABLE integration_actions DROP COLUMN IF EXISTS provider")

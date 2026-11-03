"""Presupuesto de consumo: tokens medidos, créditos facturados.

Revision ID: 184
Revises: 183

- `model_rates`: tabla de conversión tokens → créditos por modelo (con fila
  `__default__` como respaldo). Cambiar precios es insertar/actualizar filas,
  sin tocar el historial medido.
- `organization_budgets`: presupuesto mensual por organización (ventana de mes
  calendario America/Lima), umbral de alerta y bloqueo al 100 %.
"""
from __future__ import annotations

from alembic import op

revision: str = "189"
down_revision: str = "188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_rates (
            model VARCHAR(120) PRIMARY KEY,
            input_credits_per_1k NUMERIC(12, 4) NOT NULL DEFAULT 1,
            output_credits_per_1k NUMERIC(12, 4) NOT NULL DEFAULT 3,
            embedding_credits_per_1k NUMERIC(12, 4) NOT NULL DEFAULT 0.2,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO model_rates (model) VALUES ('__default__')
        ON CONFLICT (model) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO model_rates (model, input_credits_per_1k, output_credits_per_1k)
        VALUES
            ('gpt-4o-mini', 0.15, 0.6),
            ('gpt-4o', 2.5, 10),
            ('gpt-4.1-mini', 0.4, 1.6),
            ('claude-sonnet-4', 3, 15),
            ('claude-haiku-4', 1, 5)
        ON CONFLICT (model) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO model_rates (model, embedding_credits_per_1k)
        VALUES
            ('text-embedding-3-small', 0.02),
            ('text-embedding-3-large', 0.13)
        ON CONFLICT (model) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS organization_budgets (
            organization_id UUID PRIMARY KEY
                REFERENCES organizations(id) ON DELETE CASCADE,
            monthly_credits NUMERIC(14, 2) NOT NULL DEFAULT 0,
            alert_threshold NUMERIC(4, 3) NOT NULL DEFAULT 0.8,
            block_on_limit BOOLEAN NOT NULL DEFAULT TRUE,
            alert_sent_at TIMESTAMPTZ,
            blocked_at TIMESTAMPTZ,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS organization_budgets")
    op.execute("DROP TABLE IF EXISTS model_rates")

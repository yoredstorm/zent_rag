"""AI Model Budgets & Guardrails v2 — output_guardrails, circuit breakers.

Revision ID: 050
Revises: 049
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "050"
down_revision: Union[str, None] = "049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS output_guardrails (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(120) NOT NULL,
            kind VARCHAR(30) NOT NULL DEFAULT 'banned_topics',
            config JSONB NOT NULL DEFAULT '{}',
            action VARCHAR(10) NOT NULL DEFAULT 'mask',
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_output_guardrails_org "
        "ON output_guardrails(organization_id, enabled)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS model_circuit_breakers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            model_name VARCHAR(120) NOT NULL UNIQUE,
            failure_threshold INT NOT NULL DEFAULT 3,
            window_seconds INT NOT NULL DEFAULT 300,
            cooldown_seconds INT NOT NULL DEFAULT 900,
            state VARCHAR(12) NOT NULL DEFAULT 'closed',
            failures INT NOT NULL DEFAULT 0,
            last_failure_at TIMESTAMPTZ,
            opened_at TIMESTAMPTZ,
            opened_until TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO model_circuit_breakers (model_name, failure_threshold, window_seconds, cooldown_seconds) VALUES
        ('gpt-4o-mini', 3, 300, 900),
        ('gpt-4o', 3, 300, 900),
        ('zent-cheap', 5, 300, 900),
        ('zent-fast', 5, 300, 900)
        ON CONFLICT (model_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_circuit_breakers")
    op.execute("DROP TABLE IF EXISTS output_guardrails")

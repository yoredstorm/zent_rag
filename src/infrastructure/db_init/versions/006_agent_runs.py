"""Agent Runs — execution traces del Agent Runtime.

Revision ID: 006
Revises: 005
Create Date: 2026-08-21

Guarda run completo: pasos (tool calls, observaciones, final), latencias,
tokens y costo. Nunca secrets.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            agent_id UUID NOT NULL,
            user_id UUID,
            role VARCHAR(20) NOT NULL DEFAULT 'admin',
            status VARCHAR(30) NOT NULL,
            message TEXT NOT NULL,
            answer TEXT,
            steps JSONB NOT NULL DEFAULT '[]',
            total_latency_ms DOUBLE PRECISION DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost DOUBLE PRECISION DEFAULT 0,
            injection_detected BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_org "
        "ON agent_runs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_agent "
        "ON agent_runs(agent_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_runs")

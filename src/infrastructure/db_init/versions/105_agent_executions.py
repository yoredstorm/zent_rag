"""Cognitive OS — agent executions (Phase 4).

agent_executions registra cada ejecución de especialista dentro de un run
(estado, latencia, llamadas LLM, tokens, costo, resultado/error). Append y
actualización por id, scoped por organización.

Revision ID: 105
Revises: 104
"""
from __future__ import annotations

from alembic import op

revision: str = "105"
down_revision: str = "104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_executions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES cognitive_runs(id) ON DELETE CASCADE,
            task_id UUID NOT NULL REFERENCES cognitive_tasks(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id VARCHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','completed','failed','skipped')),
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            llm_calls INTEGER NOT NULL DEFAULT 0,
            tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
            error TEXT,
            result JSONB,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_executions_org_run "
        "ON agent_executions(organization_id, run_id, started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_executions_org_task "
        "ON agent_executions(organization_id, task_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_executions")

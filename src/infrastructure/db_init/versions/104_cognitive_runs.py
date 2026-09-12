"""Cognitive OS — planning runs, tasks and agent messages (Phase 3).

cognitive_runs guarda el plan (complejidad, presupuesto, scope). cognitive_tasks
persiste el DAG planificado. agent_messages es append-only y transporta
conclusiones/evidencia (nunca chain-of-thought). Puro aditivo: la ejecución de
especialistas llega en fases posteriores.

Revision ID: 104
Revises: 103
"""
from __future__ import annotations

from alembic import op

revision: str = "104"
down_revision: str = "103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cognitive_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            query TEXT NOT NULL,
            complexity VARCHAR(2) NOT NULL CHECK (complexity IN ('L0','L1','L2','L3','L4','L5')),
            status VARCHAR(16) NOT NULL DEFAULT 'planned'
                CHECK (status IN ('planned','running','completed','failed','cancelled')),
            budget JSONB NOT NULL DEFAULT '{}'::jsonb,
            scope JSONB NOT NULL DEFAULT '{}'::jsonb,
            plan JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cognitive_runs_org_created "
        "ON cognitive_runs(organization_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cognitive_runs_org_workspace "
        "ON cognitive_runs(organization_id, workspace_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cognitive_tasks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES cognitive_runs(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            task_key VARCHAR(128) NOT NULL,
            description TEXT NOT NULL,
            agent_id VARCHAR(64) NOT NULL DEFAULT '',
            status VARCHAR(16) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','ready','running','completed','failed','skipped','cancelled')),
            depends_on JSONB NOT NULL DEFAULT '[]'::jsonb,
            position INTEGER NOT NULL DEFAULT 0,
            budget JSONB NOT NULL DEFAULT '{}'::jsonb,
            input_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
            output_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
            result JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, task_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cognitive_tasks_org_run "
        "ON cognitive_tasks(organization_id, run_id, position)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_messages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES cognitive_runs(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            message_type VARCHAR(24) NOT NULL
                CHECK (message_type IN ('task','finding','evidence','question','challenge','response','conflict','handoff','final_candidate')),
            from_agent VARCHAR(64) NOT NULL,
            to_agent VARCHAR(64),
            task_key VARCHAR(128),
            text TEXT NOT NULL DEFAULT '',
            claim_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
            evidence_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
            confidence DOUBLE PRECISION,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_messages_org_run "
        "ON agent_messages(organization_id, run_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_messages")
    op.execute("DROP TABLE IF EXISTS cognitive_tasks")
    op.execute("DROP TABLE IF EXISTS cognitive_runs")

"""FASE 03 — Unified AI Trace: enriquecer agent_runs y traces con identidad
de deployment/versión/entorno, modelo, provider y trace_id.

Revision ID: 074
Revises: 073
"""
from __future__ import annotations

from alembic import op

revision: str = "074"
down_revision: str = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64),
            ADD COLUMN IF NOT EXISTS model VARCHAR(120),
            ADD COLUMN IF NOT EXISTS provider VARCHAR(60),
            ADD COLUMN IF NOT EXISTS deployment_id UUID,
            ADD COLUMN IF NOT EXISTS version_id UUID,
            ADD COLUMN IF NOT EXISTS environment VARCHAR(30),
            ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS completion_tokens INTEGER DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE traces
            ADD COLUMN IF NOT EXISTS provider VARCHAR(60),
            ADD COLUMN IF NOT EXISTS version_id UUID,
            ADD COLUMN IF NOT EXISTS environment VARCHAR(30),
            ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS completion_tokens INTEGER DEFAULT 0
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_runs_deployment "
        "ON agent_runs(deployment_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_traces_deployment "
        "ON traces(deployment_id, started_at DESC)"
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_runs
            DROP COLUMN IF EXISTS trace_id,
            DROP COLUMN IF EXISTS model,
            DROP COLUMN IF EXISTS provider,
            DROP COLUMN IF EXISTS deployment_id,
            DROP COLUMN IF EXISTS version_id,
            DROP COLUMN IF EXISTS environment,
            DROP COLUMN IF EXISTS prompt_tokens,
            DROP COLUMN IF EXISTS completion_tokens
        """
    )
    op.execute(
        """
        ALTER TABLE traces
            DROP COLUMN IF EXISTS provider,
            DROP COLUMN IF EXISTS version_id,
            DROP COLUMN IF EXISTS environment,
            DROP COLUMN IF EXISTS prompt_tokens,
            DROP COLUMN IF EXISTS completion_tokens
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_agent_runs_deployment")
    op.execute("DROP INDEX IF EXISTS idx_traces_deployment")

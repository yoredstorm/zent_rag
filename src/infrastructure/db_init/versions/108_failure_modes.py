"""Cognitive hardening — failure modes (Phase 10).

agent_executions.failure_mode registra la taxonomía de fallo (brief §52):
agent_timeout, model_failure, tool_failure, budget_limit, invalid_output,
permission_failure, retrieval_empty, unknown.

Revision ID: 108
Revises: 107
"""
from __future__ import annotations

from alembic import op

revision: str = "108"
down_revision: str = "107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agent_executions "
        "ADD COLUMN IF NOT EXISTS failure_mode VARCHAR(32)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_executions DROP COLUMN IF EXISTS failure_mode")

"""Workflow approvals — snapshot de contexto para el revisor humano (Fase 6).

Revision ID: 117
Revises: 116
"""
from __future__ import annotations

from alembic import op

revision: str = "117"
down_revision: str = "116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_approvals "
        "ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_approvals DROP COLUMN IF EXISTS context")

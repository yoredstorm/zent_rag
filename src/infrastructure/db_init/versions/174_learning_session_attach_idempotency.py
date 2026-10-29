"""Durable learning-session attach idempotency.

Revision ID: 174
Revises: 173

Additive only. Sealed sessions reject new sources at the row-lock boundary;
an optional idempotency key makes upload retries replay the existing source
instead of creating a duplicate.
"""
from __future__ import annotations

from alembic import op

revision: str = "174"
down_revision: str = "173"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE knowledge_learning_session_sources
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_learning_session_sources_idem
        ON knowledge_learning_session_sources
            (organization_id, session_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_knowledge_learning_session_sources_idem"
    )
    op.execute(
        "ALTER TABLE knowledge_learning_session_sources "
        "DROP COLUMN IF EXISTS idempotency_key"
    )

"""Learning cycle artifacts. Promotion stays manual.

Revision ID: 126
Revises: 125
"""
from __future__ import annotations

from alembic import op

revision: str = "126"
down_revision: str = "125"
branch_labels = None
depends_on = None

_EVENTS = (
    "('memory.observed','memory.created','memory.used','memory.reinforced',"
    "'memory.contradicted','memory.validated','memory.activated',"
    "'memory.deactivated','memory.rejected','memory.expired',"
    "'memory.superseded','memory.restored','memory.staled')"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_signals (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            occurred_at TIMESTAMPTZ NOT NULL,
            clustered BOOLEAN NOT NULL DEFAULT FALSE,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_learning_signals_org_time
        ON learning_signals (organization_id, occurred_at)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_artifacts (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL,
            dedupe_key VARCHAR(240) NOT NULL DEFAULT '',
            payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_artifacts_dedupe
        ON learning_artifacts (organization_id, kind, dedupe_key)
        WHERE dedupe_key <> ''
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_learning_artifacts_org_kind
        ON learning_artifacts (organization_id, kind, updated_at)
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'memory_events'
            ) THEN
                ALTER TABLE memory_events DROP CONSTRAINT IF EXISTS memory_events_event_type_check;
                ALTER TABLE memory_events
                ADD CONSTRAINT memory_events_event_type_check
                CHECK (event_type IN {_EVENTS});
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS learning_artifacts")
    op.execute("DROP TABLE IF EXISTS learning_signals")

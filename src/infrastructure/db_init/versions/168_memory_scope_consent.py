"""Memory scope, workspace, subject and consent.

Revision ID: 168
Revises: 167

Additive only. Legacy rows keep tenant-wide visibility (`scope='tenant'`) and a
NULL workspace, preserving their behavior. New rows can be workspace/user
scoped and must carry consent/expiry to be usable as long-term memory.
"""
from __future__ import annotations

from alembic import op

revision: str = "168"
down_revision: str = "167"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE memory_records
            ADD COLUMN IF NOT EXISTS workspace_id UUID,
            ADD COLUMN IF NOT EXISTS subject_id VARCHAR(160),
            ADD COLUMN IF NOT EXISTS scope VARCHAR(32) NOT NULL DEFAULT 'tenant',
            ADD COLUMN IF NOT EXISTS consent_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        ALTER TABLE memory_records
            DROP CONSTRAINT IF EXISTS memory_records_scope_check
        """
    )
    op.execute(
        """
        ALTER TABLE memory_records
            ADD CONSTRAINT memory_records_scope_check
            CHECK (scope IN (
                'tenant', 'workspace', 'participant', 'session',
                'durable_business_state', 'long_term_consent'
            ))
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_records_org_workspace_status
        ON memory_records (organization_id, workspace_id, status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_records_org_subject
        ON memory_records (organization_id, subject_id)
        """
    )
    op.execute(
        """
        DROP INDEX IF EXISTS uq_memory_live_pattern
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_live_pattern_scope
        ON memory_records (
            organization_id,
            COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
            COALESCE(subject_id, ''),
            memory_type,
            pattern_signature
        )
        WHERE status NOT IN ('rejected', 'expired', 'superseded')
          AND visibility = 'tenant'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_memory_live_pattern_scope")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_live_pattern
        ON memory_records (organization_id, memory_type, pattern_signature)
        WHERE status NOT IN ('rejected', 'expired', 'superseded')
          AND visibility = 'tenant'
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_memory_records_org_subject")
    op.execute("DROP INDEX IF EXISTS idx_memory_records_org_workspace_status")
    op.execute(
        "ALTER TABLE memory_records DROP CONSTRAINT IF EXISTS memory_records_scope_check"
    )
    op.execute(
        """
        ALTER TABLE memory_records
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS expires_at,
            DROP COLUMN IF EXISTS consent_at,
            DROP COLUMN IF EXISTS scope,
            DROP COLUMN IF EXISTS subject_id,
            DROP COLUMN IF EXISTS workspace_id
        """
    )

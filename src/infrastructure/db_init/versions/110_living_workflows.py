"""Phase LW-A — Living Workflows: data watchers (definiciones + estado).

Revision ID: 110
Revises: 109
"""
from __future__ import annotations

from alembic import op

revision: str = "110"
down_revision: str = "109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_watchers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            name VARCHAR(160) NOT NULL,
            description TEXT,
            source_id UUID,
            strategy VARCHAR(30) NOT NULL DEFAULT 'watermark_polling',
            entity VARCHAR(80) NOT NULL DEFAULT 'registro',
            schema_name VARCHAR(63),
            table_name VARCHAR(63) NOT NULL,
            primary_key VARCHAR(63),
            timestamp_field VARCHAR(63),
            selected_fields JSONB NOT NULL DEFAULT '[]',
            condition JSONB NOT NULL DEFAULT '{}',
            transition_mode VARCHAR(20) NOT NULL DEFAULT 'on_enter',
            interval_seconds INT NOT NULL DEFAULT 300,
            cooldown_seconds INT NOT NULL DEFAULT 0,
            debounce_seconds INT NOT NULL DEFAULT 0,
            event_type VARCHAR(160) NOT NULL DEFAULT '',
            entity_field VARCHAR(63),
            workflow_id UUID,
            status VARCHAR(20) NOT NULL DEFAULT 'listening',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_check_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_watchers_org "
        "ON workflow_watchers(organization_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workflow_watchers_due "
        "ON workflow_watchers(status, last_check_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_watcher_states (
            watcher_id UUID PRIMARY KEY REFERENCES workflow_watchers(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            last_value JSONB NOT NULL DEFAULT '{}',
            last_payload JSONB NOT NULL DEFAULT '{}',
            last_condition_result BOOLEAN,
            last_event_at TIMESTAMPTZ,
            last_triggered_at TIMESTAMPTZ,
            checkpoint JSONB NOT NULL DEFAULT '{}',
            cooldown_until TIMESTAMPTZ,
            pending_since TIMESTAMPTZ,
            failure_count INT NOT NULL DEFAULT 0,
            last_error TEXT,
            last_dedupe_key VARCHAR(300),
            last_check_at TIMESTAMPTZ,
            check_count INT NOT NULL DEFAULT 0,
            trigger_count INT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_watcher_states")
    op.execute("DROP TABLE IF EXISTS workflow_watchers")

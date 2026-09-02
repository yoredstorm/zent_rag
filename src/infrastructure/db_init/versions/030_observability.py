"""Observability — worker_heartbeats + incident_alerts + webhook por org.

Revision ID: 030
Revises: 029
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_name VARCHAR(80) PRIMARY KEY,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            metadata JSONB NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            deployment_id UUID,
            alert_type VARCHAR(40) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            message TEXT NOT NULL,
            threshold_value DOUBLE PRECISION,
            actual_value DOUBLE PRECISION,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            webhook_status VARCHAR(20),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_incident_alerts_org "
        "ON incident_alerts(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_incident_alerts_status "
        "ON incident_alerts(status, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS "
        "ops_webhook_url VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS "
        "ops_webhook_enabled BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS ops_webhook_enabled")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS ops_webhook_url")
    op.execute("DROP INDEX IF EXISTS idx_incident_alerts_status")
    op.execute("DROP INDEX IF EXISTS idx_incident_alerts_org")
    op.execute("DROP TABLE IF EXISTS incident_alerts")
    op.execute("DROP TABLE IF EXISTS worker_heartbeats")

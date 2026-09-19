"""Decision traces — tenant-isolated routing audit.

Revision ID: 120
Revises: 119
"""

from __future__ import annotations

from alembic import op

revision: str = "120"
down_revision: str = "119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_traces (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            request_id UUID,
            user_id UUID,
            provider VARCHAR(40) NOT NULL DEFAULT '',
            selected_capability VARCHAR(80) NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            routing_mode VARCHAR(20) NOT NULL DEFAULT 'legacy',
            actual_capability VARCHAR(80),
            jev_capability VARCHAR(80),
            agreement BOOLEAN,
            shadow BOOLEAN NOT NULL DEFAULT FALSE,
            canary BOOLEAN NOT NULL DEFAULT FALSE,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_decision_traces_org_time
        ON decision_traces (organization_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_decision_traces_created
        ON decision_traces (created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS decision_traces")

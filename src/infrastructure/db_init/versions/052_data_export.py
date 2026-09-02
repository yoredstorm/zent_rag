"""Data Export & Compliance v2 — data_exports (auditoría), retention policies.

Revision ID: 052
Revises: 051
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "052"
down_revision: Union[str, None] = "051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_exports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            export_type VARCHAR(40) NOT NULL DEFAULT 'full',
            scope VARCHAR(40) NOT NULL DEFAULT 'all',
            anonymized BOOLEAN NOT NULL DEFAULT false,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            file_key VARCHAR(300),
            size_bytes BIGINT NOT NULL DEFAULT 0,
            row_counts JSONB NOT NULL DEFAULT '{}',
            requested_by UUID,
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + interval '30 days'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_exports_org_time "
        "ON data_exports(organization_id, requested_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID,
            data_type VARCHAR(60) NOT NULL,
            retention_days INT NOT NULL DEFAULT 365,
            enabled BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, data_type)
        )
        """
    )
    op.execute(
        """
        INSERT INTO retention_policies (organization_id, data_type, retention_days) VALUES
        (NULL, 'usage_events', 365),
        (NULL, 'inference_logs', 90),
        (NULL, 'api_logs', 180),
        (NULL, 'conversations', 180),
        (NULL, 'agent_versions', 730),
        (NULL, 'audit_logs', 730)
        ON CONFLICT (organization_id, data_type) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_purges (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            policy_id UUID,
            organization_id UUID,
            data_type VARCHAR(60) NOT NULL,
            purged_rows BIGINT NOT NULL DEFAULT 0,
            ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS retention_purges")
    op.execute("DROP TABLE IF EXISTS retention_policies")
    op.execute("DROP TABLE IF EXISTS data_exports")

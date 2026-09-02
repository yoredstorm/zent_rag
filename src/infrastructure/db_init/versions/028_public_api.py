"""Public API — api_logs + hardening de API keys (ip allowlist, rate limit).

Revision ID: 028
Revises: 027
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            deployment_id UUID,
            agent_id UUID,
            request_id UUID NOT NULL,
            endpoint VARCHAR(255) NOT NULL,
            method VARCHAR(10) NOT NULL,
            status INTEGER NOT NULL,
            latency_ms DOUBLE PRECISION,
            tokens INTEGER NOT NULL DEFAULT 0,
            cost DOUBLE PRECISION,
            api_key_id UUID,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_logs_org "
        "ON api_logs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_logs_deployment "
        "ON api_logs(deployment_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS ip_allowlist JSONB "
        "NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS api_logs")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS rate_limit_per_minute")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS ip_allowlist")

"""Tenant Data Migration Tools — data_migrations con dry-run/apply/export.

Revision ID: 060
Revises: 059
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "060"
down_revision: Union[str, None] = "059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_migrations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            kind VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL DEFAULT 'import',
            status VARCHAR(20) NOT NULL DEFAULT 'dry_run',
            filename VARCHAR(300),
            rows_total INT NOT NULL DEFAULT 0,
            rows_valid INT NOT NULL DEFAULT 0,
            rows_applied INT NOT NULL DEFAULT 0,
            rows_failed INT NOT NULL DEFAULT 0,
            errors JSONB NOT NULL DEFAULT '[]',
            manifest JSONB NOT NULL DEFAULT '{}',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_migrations_org_time "
        "ON data_migrations(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS migration_staged (
            migration_id UUID PRIMARY KEY,
            content TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_migrations")

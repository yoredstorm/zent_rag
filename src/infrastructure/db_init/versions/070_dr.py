"""AI Disaster Recovery & High Availability v2.

Revision ID: 070
Revises: 069
Create Date: 2026-09-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(150) NOT NULL,
            scope VARCHAR(20) NOT NULL DEFAULT 'agent',
            target_id UUID,
            rpo_minutes INT NOT NULL DEFAULT 60,
            rto_minutes INT NOT NULL DEFAULT 15,
            replication_region VARCHAR(40) NOT NULL DEFAULT 'eu-west-1',
            status VARCHAR(15) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dr_policies_org "
        "ON dr_policies(organization_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_drills (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            policy_id UUID NOT NULL,
            region VARCHAR(40) NOT NULL,
            status VARCHAR(15) NOT NULL DEFAULT 'running',
            failover_ok BOOLEAN,
            recovery_validated BOOLEAN,
            duration_ms INT,
            detail TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dr_drills_org "
        "ON dr_drills(organization_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_backups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            scope VARCHAR(20) NOT NULL DEFAULT 'agent',
            source_id UUID,
            version INT NOT NULL DEFAULT 1,
            artifact JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(15) NOT NULL DEFAULT 'completed',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            restored_at TIMESTAMPTZ,
            restored_to_region VARCHAR(40)
        )
        """
    )
    # dr_backups pre-existió en la fase v1 (backups Qdrant) — ampliar a v2.
    op.execute(
        "ALTER TABLE dr_backups "
        "ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'agent', "
        "ADD COLUMN IF NOT EXISTS source_id UUID, "
        "ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1, "
        "ADD COLUMN IF NOT EXISTS artifact JSONB NOT NULL DEFAULT '{}', "
        "ADD COLUMN IF NOT EXISTS restored_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS restored_to_region VARCHAR(40)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dr_backups_version "
        "ON dr_backups(organization_id, scope, source_id, version)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dr_backups_org "
        "ON dr_backups(organization_id, scope, source_id, created_at DESC)"
    )


def downgrade() -> None:
    for table in ("dr_backups", "dr_drills", "dr_policies"):
        op.execute(f"DROP TABLE IF EXISTS {table}")

"""Disaster Recovery — dr_backups, catálogo de regiones, perfil DR por org.

Revision ID: 032
Revises: 031
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_regions (
            code VARCHAR(40) PRIMARY KEY,
            name VARCHAR(120) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        """
        INSERT INTO dr_regions (code, name) VALUES
        ('us-east-1', 'US East (N. Virginia)'),
        ('eu-west-1', 'EU West (Ireland)'),
        ('ap-southeast-1', 'Asia Pacific (Singapore)'),
        ('local', 'Local / On-prem')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dr_backups (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            kind VARCHAR(20) NOT NULL DEFAULT 'full',
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            trigger VARCHAR(20) NOT NULL DEFAULT 'manual',
            file_path TEXT,
            size_bytes BIGINT,
            checksum_sha256 VARCHAR(64),
            duration_ms INT,
            qdrant_snapshot BOOLEAN NOT NULL DEFAULT false,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dr_backups_org "
        "ON dr_backups(organization_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_regions JSONB "
        "NOT NULL DEFAULT '[]'"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_rpo_minutes INT "
        "NOT NULL DEFAULT 1440"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_backup_enabled BOOLEAN "
        "NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS dr_backup_enabled")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS dr_rpo_minutes")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS dr_regions")
    op.execute("DROP INDEX IF EXISTS idx_dr_backups_org")
    op.execute("DROP TABLE IF EXISTS dr_backups")
    op.execute("DROP TABLE IF EXISTS dr_regions")

"""Multi-Region & Edge Caching — regions, region_replicas, org primary_region.

Revision ID: 047
Revises: 046
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS regions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code VARCHAR(40) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            priority INT NOT NULL DEFAULT 10,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO regions (code, name, status, priority) VALUES
        ('us-east-1', 'US East (N. Virginia)', 'active', 10),
        ('eu-west-1', 'EU West (Ireland)', 'active', 20),
        ('ap-southeast-1', 'Asia Pacific (Singapore)', 'active', 30),
        ('sa-east-1', 'South America (São Paulo)', 'active', 40)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS region_replicas (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            region_id UUID NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
            kind VARCHAR(20) NOT NULL DEFAULT 'postgres',
            endpoint VARCHAR(200) NOT NULL DEFAULT 'local',
            healthy BOOLEAN NOT NULL DEFAULT true,
            last_latency_ms DOUBLE PRECISION,
            last_health_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO region_replicas (region_id, kind, endpoint)
        SELECT r.id, 'postgres', 'local' FROM regions r ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS primary_region_id UUID"
    )
    op.execute(
        """
        UPDATE organizations SET primary_region_id = r.id
        FROM regions r WHERE r.code = 'us-east-1'
        AND primary_region_id IS NULL
        """
    )
    op.execute(
        "ALTER TABLE inference_logs ADD COLUMN IF NOT EXISTS region VARCHAR(40)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE inference_logs DROP COLUMN IF EXISTS region")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS primary_region_id")
    op.execute("DROP TABLE IF EXISTS region_replicas")
    op.execute("DROP TABLE IF EXISTS regions")

"""AI Security Operations Center (SOC) v2.

Revision ID: 068
Revises: 067
Create Date: 2026-09-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            event_type VARCHAR(30) NOT NULL,
            severity VARCHAR(15) NOT NULL DEFAULT 'low',
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL DEFAULT 'detected',
            evidence JSONB NOT NULL DEFAULT '{}',
            timeline JSONB NOT NULL DEFAULT '[]',
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_events_org "
        "ON security_events(organization_id, status, score DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_responses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id UUID NOT NULL,
            action_type VARCHAR(20) NOT NULL,
            target VARCHAR(120),
            status VARCHAR(15) NOT NULL DEFAULT 'executed',
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_responses_event "
        "ON security_responses(event_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_posture_snapshots (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            date DATE NOT NULL,
            threat_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            open_events INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, date)
        )
        """
    )
    # Permite bloquear deployments como respuesta automática.
    op.execute(
        "ALTER TABLE deployments DROP CONSTRAINT IF EXISTS deployments_status_check"
    )
    op.execute(
        "ALTER TABLE deployments ADD CONSTRAINT deployments_status_check CHECK "
        "(status IN ('pending', 'deploying', 'healthy', 'degraded', 'failed', "
        "'rolled_back', 'blocked'))"
    )
    # Factor de throttling para respuestas automáticas del SOC.
    op.execute(
        "ALTER TABLE rate_limit_rules "
        "ADD COLUMN IF NOT EXISTS throttle_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0"
    )


def downgrade() -> None:
    for table in ("security_posture_snapshots", "security_responses", "security_events"):
        op.execute(f"DROP TABLE IF EXISTS {table}")

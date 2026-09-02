"""Tenant Onboarding Experience v2 — progress + events de activación.

Revision ID: 058
Revises: 057
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "058"
down_revision: Union[str, None] = "057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_progress (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL UNIQUE,
            steps JSONB NOT NULL DEFAULT '{}',
            current_step VARCHAR(40) NOT NULL DEFAULT 'create_kb',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            time_to_first_value_seconds DOUBLE PRECISION,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS onboarding_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            step VARCHAR(40) NOT NULL,
            event_type VARCHAR(20) NOT NULL DEFAULT 'step_done',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_onboarding_events_step "
        "ON onboarding_events(step, event_type, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS onboarding_events")
    op.execute("DROP TABLE IF EXISTS onboarding_progress")

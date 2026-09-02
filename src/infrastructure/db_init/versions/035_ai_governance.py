"""AI Governance — anomaly_events, prompt_revisions, políticas AI por org.

Revision ID: 035
Revises: 034
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS anomaly_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID,
            anomaly_type VARCHAR(40) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            message TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acknowledged_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_anomaly_events_type "
        "ON anomaly_events(anomaly_type, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_revisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            prompt_key VARCHAR(120) NOT NULL,
            organization_id UUID NOT NULL,
            version INT NOT NULL,
            content TEXT NOT NULL,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_prompt_revisions_key "
        "ON prompt_revisions(prompt_key, organization_id, version DESC)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ai_pii_masking_enabled "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ai_guardrails JSONB "
        "NOT NULL DEFAULT '{}'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS ai_guardrails")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS ai_pii_masking_enabled")
    op.execute("DROP INDEX IF EXISTS idx_prompt_revisions_key")
    op.execute("DROP TABLE IF EXISTS prompt_revisions")
    op.execute("DROP INDEX IF EXISTS idx_anomaly_events_type")
    op.execute("DROP TABLE IF EXISTS anomaly_events")

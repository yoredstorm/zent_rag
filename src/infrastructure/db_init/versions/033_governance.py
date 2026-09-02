"""Governance — retention, residencia de datos, DSR (GDPR), KMS envelope.

Revision ID: 033
Revises: 032
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS retention_days INT "
        "NOT NULL DEFAULT 365"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS data_residency_region VARCHAR(40)"
    )
    op.execute(
        "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dsr_contact_email VARCHAR(320)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS compliance_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            event_type VARCHAR(40) NOT NULL,
            actor_user_id UUID,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_compliance_org "
        "ON compliance_events(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kms_keys (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(120) NOT NULL,
            key_version INT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            dek_enc VARCHAR(600) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            rotated_at TIMESTAMPTZ,
            retired_at TIMESTAMPTZ,
            UNIQUE (key_version)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kms_keys")
    op.execute("DROP INDEX IF EXISTS idx_compliance_org")
    op.execute("DROP TABLE IF EXISTS compliance_events")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS dsr_contact_email")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS data_residency_region")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS retention_days")

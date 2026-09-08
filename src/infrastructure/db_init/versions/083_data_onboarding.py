"""PHASE 31A — Data Onboarding Wizard sessions.

Revision ID: 083
Revises: 082
"""
from __future__ import annotations

from alembic import op

revision: str = "083"
down_revision: str = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_onboarding_sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            created_by UUID,
            kind VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'NOT_STARTED',
            step VARCHAR(32) NOT NULL DEFAULT 'choose',
            connector_id UUID,
            catalog_source_id UUID,
            kb_source_id UUID,
            skipped_review BOOLEAN NOT NULL DEFAULT false,
            skipped_test BOOLEAN NOT NULL DEFAULT false,
            state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_onboarding_sessions_org "
        "ON data_onboarding_sessions(organization_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_onboarding_sessions")

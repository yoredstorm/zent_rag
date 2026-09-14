"""Living Assistants UX — inbox: acknowledge de business results.

Revision ID: 114
Revises: 113
"""
from __future__ import annotations

from alembic import op

revision: str = "114"
down_revision: str = "113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE business_results ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS acknowledged_by UUID"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_results_inbox "
        "ON business_results(organization_id, acknowledged_at, generated_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_business_results_inbox")
    op.execute(
        "ALTER TABLE business_results DROP COLUMN IF EXISTS acknowledged_at, "
        "DROP COLUMN IF EXISTS acknowledged_by"
    )

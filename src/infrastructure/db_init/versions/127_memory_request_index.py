"""Index memory events by tenant and decision request.

Revision ID: 127
Revises: 126
"""
from __future__ import annotations

from alembic import op

revision: str = "127"
down_revision: str = "126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_events_org_request
        ON memory_events (organization_id, request_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_memory_events_org_request")

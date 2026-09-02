"""Security Center — findings de secretos/leaks.

Revision ID: 040
Revises: 039
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_findings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID,
            finding_type VARCHAR(40) NOT NULL,
            severity VARCHAR(20) NOT NULL DEFAULT 'warning',
            target_type VARCHAR(40) NOT NULL,
            target_id VARCHAR(80),
            detail TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_security_findings_org "
        "ON security_findings(organization_id, status, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_security_findings_org")
    op.execute("DROP TABLE IF EXISTS security_findings")

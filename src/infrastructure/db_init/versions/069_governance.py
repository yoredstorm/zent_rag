"""AI Governance Board & Audit Trail v2.

Revision ID: 069
Revises: 068
Create Date: 2026-09-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            policy_type VARCHAR(30) NOT NULL DEFAULT 'acceptable_use',
            name VARCHAR(150) NOT NULL,
            content TEXT NOT NULL,
            version INT NOT NULL DEFAULT 1,
            status VARCHAR(15) NOT NULL DEFAULT 'active',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_governance_policies_org "
        "ON governance_policies(organization_id, policy_type)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            decision_type VARCHAR(30) NOT NULL DEFAULT 'deploy_approval',
            target_id UUID,
            title VARCHAR(200) NOT NULL,
            rationale TEXT,
            status VARCHAR(15) NOT NULL DEFAULT 'pending',
            approvers JSONB NOT NULL DEFAULT '[]',
            required_approvals INT NOT NULL DEFAULT 2,
            decided_by UUID,
            decided_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_governance_decisions_org "
        "ON governance_decisions(organization_id, status, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS governance_audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            actor_id UUID,
            actor_name VARCHAR(150),
            action VARCHAR(40) NOT NULL,
            entity_type VARCHAR(40) NOT NULL,
            entity_id UUID,
            detail TEXT,
            prev_hash VARCHAR(64) NOT NULL DEFAULT '',
            hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_governance_audit_org "
        "ON governance_audit_log(organization_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS team_certifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            member_name VARCHAR(150) NOT NULL,
            certification VARCHAR(40) NOT NULL,
            issued_at DATE NOT NULL DEFAULT CURRENT_DATE,
            expires_at DATE NOT NULL DEFAULT CURRENT_DATE + interval '1 year',
            status VARCHAR(15) NOT NULL DEFAULT 'valid',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_team_certifications_org "
        "ON team_certifications(organization_id, status)"
    )


def downgrade() -> None:
    for table in (
        "team_certifications",
        "governance_audit_log",
        "governance_decisions",
        "governance_policies",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")

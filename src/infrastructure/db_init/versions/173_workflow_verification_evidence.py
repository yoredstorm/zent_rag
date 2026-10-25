"""Verification evidence for sandbox/provider certification.

Revision ID: 173
Revises: 172

Aditiva. La evidencia la produce un adaptador del servidor; nunca un flag de
workflow.metadata. Sin adaptador real configurado, sandbox/provider se bloquean.
"""
from __future__ import annotations

from alembic import op

revision: str = "173"
down_revision: str = "172"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_certificates "
        "ADD COLUMN IF NOT EXISTS verification_id UUID, "
        "ADD COLUMN IF NOT EXISTS environment VARCHAR(40) NOT NULL DEFAULT 'design'"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_verification_evidence (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL,
            level VARCHAR(30) NOT NULL,
            state VARCHAR(40) NOT NULL,
            environment VARCHAR(40) NOT NULL,
            graph_hash VARCHAR(64) NOT NULL,
            plan_hash VARCHAR(64) NOT NULL DEFAULT '',
            binding_fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            policy_version VARCHAR(40) NOT NULL DEFAULT 'v1',
            provider_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            scenarios JSONB NOT NULL DEFAULT '[]'::jsonb,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            side_effect_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            duration_ms INT NOT NULL DEFAULT 0,
            issued_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revoked_reason VARCHAR(300)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_verification_lookup "
        "ON workflow_verification_evidence(organization_id, workflow_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_verification_hash "
        "ON workflow_verification_evidence(organization_id, workflow_id, graph_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_verification_hash")
    op.execute("DROP INDEX IF EXISTS idx_wf_verification_lookup")
    op.execute("DROP TABLE IF EXISTS workflow_verification_evidence")
    op.execute(
        "ALTER TABLE workflow_certificates "
        "DROP COLUMN IF EXISTS environment, "
        "DROP COLUMN IF EXISTS verification_id"
    )

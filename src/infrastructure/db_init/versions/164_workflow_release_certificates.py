"""Workflow release policy and server-issued certificates.

Revision ID: 164
Revises: 163

Aditiva:
- workflows.release_policy / reason / timestamp (legacy explícito, no bypass
  implícito por metadata ausente);
- workflow_versions.certificate_id (trazabilidad de la evidencia usada);
- workflow_certificates (certificado inmutable emitido por backend).

No reescribe históricos: los workflows existentes quedan marcados 'legacy' con
razón y fecha; los nuevos usan el default 'standard'.
"""
from __future__ import annotations

from alembic import op

revision: str = "164"
down_revision: str = "163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy "
        "VARCHAR(20) NOT NULL DEFAULT 'standard'"
    )
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy_reason TEXT"
    )
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS release_policy_at TIMESTAMPTZ"
    )
    # Marca única y auditable del baseline anterior a este gate.
    op.execute(
        "UPDATE workflows SET release_policy = 'legacy', "
        "release_policy_reason = 'política legacy registrada en migración 164', "
        "release_policy_at = NOW() "
        "WHERE release_policy = 'standard' AND release_policy_at IS NULL"
    )
    op.execute(
        "ALTER TABLE workflow_versions ADD COLUMN IF NOT EXISTS certificate_id UUID"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_certificates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            workflow_version INTEGER,
            release_version INTEGER,
            risk_class VARCHAR(30) NOT NULL,
            level VARCHAR(30) NOT NULL,
            state VARCHAR(40) NOT NULL,
            graph_hash VARCHAR(64) NOT NULL,
            semantic_plan_hash VARCHAR(64) NOT NULL DEFAULT '',
            capability_snapshot_hash VARCHAR(64) NOT NULL DEFAULT '',
            agent_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
            role_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
            policy_version VARCHAR(40) NOT NULL DEFAULT 'v1',
            scenarios JSONB NOT NULL DEFAULT '[]'::jsonb,
            results JSONB NOT NULL DEFAULT '{}'::jsonb,
            provider_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            approvals JSONB NOT NULL DEFAULT '[]'::jsonb,
            issued_by UUID,
            issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            revoked_reason VARCHAR(300)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_cert_lookup "
        "ON workflow_certificates(organization_id, workflow_id, graph_hash, issued_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_cert_workspace "
        "ON workflow_certificates(organization_id, workspace_id, workflow_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_cert_workspace")
    op.execute("DROP INDEX IF EXISTS idx_wf_cert_lookup")
    op.execute("DROP TABLE IF EXISTS workflow_certificates")
    op.execute("ALTER TABLE workflow_versions DROP COLUMN IF EXISTS certificate_id")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS release_policy_at")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS release_policy_reason")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS release_policy")

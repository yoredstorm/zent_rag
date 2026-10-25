"""Effective execution policy and role revocations.

Revision ID: 172
Revises: 171

Aditiva. El scope de capacidades se congela por workflow/solución; el runtime
evalúa la intersección RBAC ∩ scope ∩ rol ∩ bindings. Los workflows históricos
reciben el scope que ya podían ejecutar, marcado como baseline auditable.
"""
from __future__ import annotations

from alembic import op

revision: str = "172"
down_revision: str = "171"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflows "
        "ADD COLUMN IF NOT EXISTS capability_scope JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "ADD COLUMN IF NOT EXISTS capability_scope_source VARCHAR(30) NOT NULL DEFAULT 'unset', "
        "ADD COLUMN IF NOT EXISTS safety_profile VARCHAR(30) NOT NULL DEFAULT 'standard', "
        "ADD COLUMN IF NOT EXISTS policy_version VARCHAR(40) NOT NULL DEFAULT 'v1', "
        "ADD COLUMN IF NOT EXISTS solution_id UUID"
    )
    op.execute(
        "ALTER TABLE workflow_runs "
        "ADD COLUMN IF NOT EXISTS effective_policy JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN IF NOT EXISTS effective_scope_hash VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE workflow_instances "
        "ADD COLUMN IF NOT EXISTS policy_hash VARCHAR(64)"
    )

    op.execute(
        """
        UPDATE workflows w
        SET capability_scope = COALESCE((
                SELECT jsonb_agg(DISTINCT ref)
                FROM (
                    SELECT COALESCE(
                        node->'config'->>'capability',
                        node->'config'->>'capability_ref',
                        node->'config'->>'action_id'
                    ) AS ref
                    FROM jsonb_array_elements(COALESCE(w.graph->'nodes', '[]'::jsonb)) AS node
                    WHERE COALESCE(node->>'type', '') IN (
                        'capability_call', 'marketplace_action', 'api_call', 'business_node'
                    )
                ) refs
                WHERE ref IS NOT NULL AND ref <> ''
            ), '[]'::jsonb),
            capability_scope_source = 'legacy_baseline'
        WHERE w.capability_scope = '[]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE workflows w
        SET solution_id = s.id
        FROM studio_solutions s
        WHERE s.organization_id = w.organization_id
          AND s.slug = w.graph->'metadata'->>'solution_ref'
          AND w.solution_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE workflows w
        SET safety_profile = 'wellness'
        WHERE w.safety_profile = 'standard'
          AND EXISTS (
              SELECT 1 FROM studio_solutions s
              WHERE s.organization_id = w.organization_id
                AND s.slug = w.graph->'metadata'->>'solution_ref'
                AND (s.blueprint::text ILIKE '%wellness%'
                     OR s.blueprint::text ILIKE '%clinical%')
          )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_capability_scope "
        "ON workflows(organization_id, workspace_id, solution_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_policy_revocations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            scope_type VARCHAR(30) NOT NULL,
            scope_id UUID,
            capability_ref VARCHAR(120),
            reason VARCHAR(300) NOT NULL,
            revoked_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            active BOOLEAN NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_policy_revocations_active "
        "ON workflow_policy_revocations(organization_id, active, capability_ref)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_policy_revocations_active")
    op.execute("DROP TABLE IF EXISTS workflow_policy_revocations")
    op.execute("DROP INDEX IF EXISTS idx_wf_capability_scope")
    op.execute(
        "ALTER TABLE workflow_instances DROP COLUMN IF EXISTS policy_hash"
    )
    op.execute(
        "ALTER TABLE workflow_runs "
        "DROP COLUMN IF EXISTS effective_scope_hash, "
        "DROP COLUMN IF EXISTS effective_policy"
    )
    op.execute(
        "ALTER TABLE workflows "
        "DROP COLUMN IF EXISTS solution_id, "
        "DROP COLUMN IF EXISTS policy_version, "
        "DROP COLUMN IF EXISTS safety_profile, "
        "DROP COLUMN IF EXISTS capability_scope_source, "
        "DROP COLUMN IF EXISTS capability_scope"
    )

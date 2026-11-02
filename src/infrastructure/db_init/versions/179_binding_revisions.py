"""P19.1-03 - revision y hash verificable de bindings de datos.

Revision ID: 179
Revises: 178

Aditiva. El binding gana version/hash de plan y una tabla de revisiones para
que una referencia logica no cambie de recursos en silencio. Los workflows
antiguos sin hash siguen siendo legibles (modo legacy explicito).
"""
from __future__ import annotations

from alembic import op

revision: str = "179"
down_revision: str = "178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_capability_bindings "
        "ADD COLUMN IF NOT EXISTS plan_version INTEGER NOT NULL DEFAULT 1, "
        "ADD COLUMN IF NOT EXISTS canonical_plan_hash VARCHAR(64), "
        "ADD COLUMN IF NOT EXISTS policy_version VARCHAR(40) NOT NULL DEFAULT 'v1', "
        "ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_capability_binding_revisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            binding_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            workspace_id UUID,
            plan_version INTEGER NOT NULL,
            canonical_plan_hash VARCHAR(64),
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'published',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (binding_id, plan_version)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_binding_revisions_org "
        "ON workflow_capability_binding_revisions(organization_id, workspace_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_capability_binding_revisions")
    for column in ("superseded_at", "policy_version", "canonical_plan_hash", "plan_version"):
        op.execute(f"ALTER TABLE workflow_capability_bindings DROP COLUMN IF EXISTS {column}")

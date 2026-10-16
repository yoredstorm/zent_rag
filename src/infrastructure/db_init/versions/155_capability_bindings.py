"""Capability bindings - binding logico por tenant de capacidades de negocio.

Revision ID: 155
Revises: 154

Aditiva. Un workflow portable depende de capacidades logicas
(catalog.products.search, payments.checkout.create, ...); el binding resuelve
esa capacidad contra un provider concreto del tenant (managed db, connected db,
accion de marketplace, semantic query, REST, ERP). El runtime de ejecucion
sigue siendo execute_action cuando el provider es marketplace_action.
"""
from __future__ import annotations

from alembic import op

revision: str = "155"
down_revision: str = "154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_capability_bindings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            capability_ref VARCHAR(120) NOT NULL,
            provider_kind VARCHAR(40) NOT NULL,
            config JSONB NOT NULL DEFAULT '{}',
            credential_ref VARCHAR(160),
            contract_input_schema JSONB NOT NULL DEFAULT '{}',
            contract_output_schema JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_bindings_capability "
        "ON workflow_capability_bindings(organization_id, workspace_id, capability_ref) "
        "WHERE workspace_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_bindings_capability_org "
        "ON workflow_capability_bindings(organization_id, capability_ref) "
        "WHERE workspace_id IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_bindings_org "
        "ON workflow_capability_bindings(organization_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_bindings_org")
    op.execute("DROP INDEX IF EXISTS uq_wf_bindings_capability_org")
    op.execute("DROP INDEX IF EXISTS uq_wf_bindings_capability")
    op.execute("DROP TABLE IF EXISTS workflow_capability_bindings")

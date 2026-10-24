"""Durable ingress inbox and idempotent instance starts.

Revision ID: 165
Revises: 164

Aditiva:
- workflow_instances.ingress_key + unique partial index;
- workflow_ingress_events (inbox para triggers durables y reintentos).

La clave de ingreso es distinta de business_key: identifica el evento de
entrada (webhook/schedule/event), no la operación de negocio.
"""
from __future__ import annotations

from alembic import op

revision: str = "165"
down_revision: str = "164"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_instances ADD COLUMN IF NOT EXISTS ingress_key VARCHAR(200)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_instances_ingress "
        "ON workflow_instances(organization_id, workflow_id, ingress_key) "
        "WHERE ingress_key IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_ingress_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
            trigger_type VARCHAR(40) NOT NULL,
            ingress_key VARCHAR(200) NOT NULL,
            external_event_id VARCHAR(200),
            business_key VARCHAR(200),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            instance_id UUID,
            attempts INT NOT NULL DEFAULT 0,
            last_error VARCHAR(400),
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_at TIMESTAMPTZ,
            processed_at TIMESTAMPTZ,
            UNIQUE (organization_id, ingress_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_ingress_status "
        "ON workflow_ingress_events(organization_id, status, received_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_ingress_workflow "
        "ON workflow_ingress_events(organization_id, workflow_id, received_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_ingress_workflow")
    op.execute("DROP INDEX IF EXISTS idx_wf_ingress_status")
    op.execute("DROP TABLE IF EXISTS workflow_ingress_events")
    op.execute("DROP INDEX IF EXISTS uq_wf_instances_ingress")
    op.execute("ALTER TABLE workflow_instances DROP COLUMN IF EXISTS ingress_key")

"""Workflow Instances - procesos de negocio durables sobre el motor v2.

Revision ID: 153
Revises: 152

Aditiva: tablas y columnas nuevas, sin renombrar ni eliminar nada.

- workflow_instances: proceso de negocio vivo (Definition / Instance / Run).
  Cada instancia congela la version del workflow con la que nacio
  (definition_snapshot) y guarda el estado de negocio durable (state JSONB).
  Los runs dejan de ser el proceso: son segmentos entre checkpoints.
- workflow_runs.instance_id / instance_seq: liga suave (nullable) del segmento
  a su instancia. Los runs existentes sin instance siguen identicos.
- workflow_run_events.instance_id: timeline unificado de instancia.
"""
from __future__ import annotations

from alembic import op

revision: str = "153"
down_revision: str = "152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_instances (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL,
            workflow_version INT NOT NULL DEFAULT 1,
            definition_snapshot JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'NEW',
            conversation_id UUID,
            participant_id VARCHAR(160),
            business_key VARCHAR(200),
            current_node_id VARCHAR(80),
            state JSONB NOT NULL DEFAULT '{}',
            state_version INT NOT NULL DEFAULT 0,
            waiting_for JSONB NOT NULL DEFAULT '{}',
            waiting_event_type VARCHAR(120),
            waiting_correlation_key VARCHAR(200),
            wait_deadline TIMESTAMPTZ,
            wait_seq INT NOT NULL DEFAULT 0,
            last_run_id UUID,
            run_seq INT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            correlation_id VARCHAR(128),
            created_by UUID,
            error TEXT,
            status_reason VARCHAR(200)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_org_status "
        "ON workflow_instances(organization_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_org_wf "
        "ON workflow_instances(organization_id, workflow_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_conv "
        "ON workflow_instances(organization_id, conversation_id) "
        "WHERE conversation_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_instances_business_key "
        "ON workflow_instances(organization_id, business_key) "
        "WHERE business_key IS NOT NULL "
        "AND status IN ('NEW', 'RUNNING', 'WAITING', 'SUSPENDED')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_wait "
        "ON workflow_instances(organization_id, waiting_event_type, waiting_correlation_key) "
        "WHERE status = 'WAITING'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_wait_deadline "
        "ON workflow_instances(wait_deadline) "
        "WHERE status = 'WAITING' AND wait_deadline IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_instances_expires "
        "ON workflow_instances(expires_at) "
        "WHERE expires_at IS NOT NULL "
        "AND status IN ('NEW', 'RUNNING', 'WAITING', 'SUSPENDED')"
    )
    op.execute(
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS instance_id UUID"
    )
    op.execute(
        "ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS instance_seq INT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_runs_instance "
        "ON workflow_runs(instance_id, started_at) "
        "WHERE instance_id IS NOT NULL"
    )
    op.execute(
        "ALTER TABLE workflow_run_events ADD COLUMN IF NOT EXISTS instance_id UUID"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_run_events_instance "
        "ON workflow_run_events(instance_id, created_at) "
        "WHERE instance_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_run_events_instance")
    op.execute("ALTER TABLE workflow_run_events DROP COLUMN IF EXISTS instance_id")
    op.execute("DROP INDEX IF EXISTS idx_wf_runs_instance")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS instance_seq")
    op.execute("ALTER TABLE workflow_runs DROP COLUMN IF EXISTS instance_id")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_expires")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_wait_deadline")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_wait")
    op.execute("DROP INDEX IF EXISTS uq_wf_instances_business_key")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_conv")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_org_wf")
    op.execute("DROP INDEX IF EXISTS idx_wf_instances_org_status")
    op.execute("DROP TABLE IF EXISTS workflow_instances")

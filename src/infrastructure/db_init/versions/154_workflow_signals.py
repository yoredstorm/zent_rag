"""Workflow signals - inbox durable de eventos para instancias.

Revision ID: 154
Revises: 153

Aditiva. Un signal es un evento externo persistido (mensaje, webhook, pago,
timer) que despierta o alimenta una WorkflowInstance. La idempotencia vive en
la tabla: el mismo evento externo jamas se procesa dos veces.

- external_event_id: id del proveedor (Stripe event id, message id...).
- idempotency_key: clave interna derivada (p. ej. timeout:{instance}:{wait_seq}).
- correlation_key: normalizacion de la correlacion del wait (k=v ordenadas).
"""
from __future__ import annotations

from alembic import op

revision: str = "154"
down_revision: str = "153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_signals (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            event_type VARCHAR(120) NOT NULL,
            external_event_id VARCHAR(200),
            idempotency_key VARCHAR(200),
            correlation_key VARCHAR(200),
            payload JSONB NOT NULL DEFAULT '{}',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            instance_id UUID,
            instance_run_id UUID,
            source VARCHAR(40) NOT NULL DEFAULT 'internal',
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            claimed_at TIMESTAMPTZ,
            consumed_at TIMESTAMPTZ,
            discarded_reason VARCHAR(200)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_signals_external "
        "ON workflow_signals(organization_id, event_type, external_event_id) "
        "WHERE external_event_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_signals_idem "
        "ON workflow_signals(organization_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_signals_match "
        "ON workflow_signals(organization_id, event_type, correlation_key, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_signals_instance "
        "ON workflow_signals(instance_id, received_at) "
        "WHERE instance_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_signals_received "
        "ON workflow_signals(organization_id, received_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_signals_received")
    op.execute("DROP INDEX IF EXISTS idx_wf_signals_instance")
    op.execute("DROP INDEX IF EXISTS idx_wf_signals_match")
    op.execute("DROP INDEX IF EXISTS uq_wf_signals_idem")
    op.execute("DROP INDEX IF EXISTS uq_wf_signals_external")
    op.execute("DROP TABLE IF EXISTS workflow_signals")

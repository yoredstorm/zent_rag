"""Durable event identity, inbox leases and transactional outbox.

Revision ID: 171
Revises: 170

Aditiva. La identidad del evento deja de depender del hash del payload:
`dedupe_key` se calcula por fuente (provider/client/schedule/event). Las filas
históricas conservan `ingress_key` como dedupe legacy.
"""
from __future__ import annotations

from alembic import op

revision: str = "171"
down_revision: str = "170"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_ingress_events "
        "ADD COLUMN IF NOT EXISTS source VARCHAR(40), "
        "ADD COLUMN IF NOT EXISTS event_type VARCHAR(120), "
        "ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(200), "
        "ADD COLUMN IF NOT EXISTS payload_hash VARCHAR(64) NOT NULL DEFAULT '', "
        "ADD COLUMN IF NOT EXISTS dedupe_mode VARCHAR(30) NOT NULL DEFAULT 'legacy', "
        "ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(240), "
        "ADD COLUMN IF NOT EXISTS envelope JSONB NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
        "ADD COLUMN IF NOT EXISTS max_attempts INT NOT NULL DEFAULT 8, "
        "ADD COLUMN IF NOT EXISTS dead_letter_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS effect_status VARCHAR(20) NOT NULL DEFAULT 'none', "
        "ADD COLUMN IF NOT EXISTS run_id UUID"
    )
    op.execute(
        "UPDATE workflow_ingress_events SET source = COALESCE(trigger_type, 'legacy') "
        "WHERE source IS NULL"
    )
    op.execute(
        "UPDATE workflow_ingress_events SET dedupe_key = ingress_key "
        "WHERE dedupe_key IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_ingress_dedupe "
        "ON workflow_ingress_events(organization_id, workflow_id, source, dedupe_key) "
        "WHERE dedupe_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_ingress_drain "
        "ON workflow_ingress_events(status, next_attempt_at, received_at) "
        "WHERE status IN ('pending', 'failed')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_ingress_dead_letter "
        "ON workflow_ingress_events(organization_id, dead_letter_at) "
        "WHERE dead_letter_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_ingress_provider "
        "ON workflow_ingress_events(organization_id, provider_event_id) "
        "WHERE provider_event_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            aggregate_type VARCHAR(60) NOT NULL,
            aggregate_key VARCHAR(200) NOT NULL,
            event_id UUID NOT NULL,
            event_type VARCHAR(120) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            headers JSONB NOT NULL DEFAULT '{}'::jsonb,
            available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at TIMESTAMPTZ,
            attempts INT NOT NULL DEFAULT 0,
            last_error VARCHAR(400),
            lease_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_outbox_dispatch "
        "ON workflow_outbox(available_at, created_at) WHERE delivered_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_outbox_aggregate "
        "ON workflow_outbox(organization_id, aggregate_type, aggregate_key, created_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_effect_intents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            workflow_id UUID NOT NULL,
            instance_id UUID,
            node_id VARCHAR(80) NOT NULL,
            capability_ref VARCHAR(120) NOT NULL,
            effect_id VARCHAR(128) NOT NULL,
            external_id VARCHAR(200),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            request_hash VARCHAR(64) NOT NULL,
            response JSONB NOT NULL DEFAULT '{}'::jsonb,
            attempts INT NOT NULL DEFAULT 0,
            last_error VARCHAR(400),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, effect_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_effect_intents_status "
        "ON workflow_effect_intents(organization_id, status, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workflow_effect_intents")
    op.execute("DROP TABLE IF EXISTS workflow_outbox")
    op.execute("DROP INDEX IF EXISTS idx_wf_ingress_provider")
    op.execute("DROP INDEX IF EXISTS idx_wf_ingress_dead_letter")
    op.execute("DROP INDEX IF EXISTS idx_wf_ingress_drain")
    op.execute("DROP INDEX IF EXISTS uq_wf_ingress_dedupe")
    op.execute(
        "ALTER TABLE workflow_ingress_events "
        "DROP COLUMN IF EXISTS run_id, "
        "DROP COLUMN IF EXISTS effect_status, "
        "DROP COLUMN IF EXISTS dead_letter_at, "
        "DROP COLUMN IF EXISTS max_attempts, "
        "DROP COLUMN IF EXISTS next_attempt_at, "
        "DROP COLUMN IF EXISTS lease_expires_at, "
        "DROP COLUMN IF EXISTS heartbeat_at, "
        "DROP COLUMN IF EXISTS envelope, "
        "DROP COLUMN IF EXISTS dedupe_key, "
        "DROP COLUMN IF EXISTS dedupe_mode, "
        "DROP COLUMN IF EXISTS payload_hash, "
        "DROP COLUMN IF EXISTS provider_event_id, "
        "DROP COLUMN IF EXISTS event_type, "
        "DROP COLUMN IF EXISTS source"
    )

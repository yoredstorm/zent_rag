"""Memory foundation — records, append-only events, evidence links.

Revision ID: 125
Revises: 124

Tenant-private. visibility='product' queda reservada y esta fase no la escribe.
ACTIVE no autoriza mutar prompts, thresholds, modelos ni configuración.
"""
from __future__ import annotations

from alembic import op

revision: str = "125"
down_revision: str = "124"
branch_labels = None
depends_on = None

_TYPES = "('conversation','knowledge','operational','learning')"
_STATUS = (
    "('observed','reinforced','pattern','validated','active',"
    "'contradicted','stale','rejected','expired','superseded')"
)
_EVENTS = (
    "('memory.observed','memory.created','memory.used','memory.reinforced',"
    "'memory.contradicted','memory.validated','memory.activated',"
    "'memory.deactivated','memory.rejected','memory.expired',"
    "'memory.superseded','memory.restored','memory.staled')"
)
_KINDS = (
    "('conversation','run','decision_trace','retrieval','agent_result',"
    "'tool_result','experiment','claim','evidence_ledger')"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS memory_records (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            visibility VARCHAR(16) NOT NULL DEFAULT 'tenant'
                CHECK (visibility IN ('tenant','product')),
            memory_type VARCHAR(24) NOT NULL CHECK (memory_type IN {_TYPES}),
            title VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            pattern_key VARCHAR(80) NOT NULL,
            pattern_signature VARCHAR(320) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'observed'
                CHECK (status IN {_STATUS}),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            support_count INT NOT NULL DEFAULT 0,
            contradiction_count INT NOT NULL DEFAULT 0,
            success_count INT NOT NULL DEFAULT 0,
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            validated_at TIMESTAMPTZ,
            activated_at TIMESTAMPTZ,
            created_from_conversation_id UUID,
            created_from_run_id UUID,
            intent_family VARCHAR(80) NOT NULL DEFAULT '',
            source_type VARCHAR(80) NOT NULL DEFAULT '',
            retrieval_modality VARCHAR(80) NOT NULL DEFAULT '',
            tool_family VARCHAR(80) NOT NULL DEFAULT '',
            failure_category VARCHAR(80) NOT NULL DEFAULT '',
            success_signal VARCHAR(80) NOT NULL DEFAULT '',
            source_component VARCHAR(80) NOT NULL DEFAULT '',
            agent_id UUID,
            workflow_id UUID,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            version INT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_records_org_type_status
        ON memory_records (organization_id, memory_type, status)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_records_org_signature
        ON memory_records (organization_id, pattern_signature)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_records_org_updated
        ON memory_records (organization_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_live_pattern
        ON memory_records (organization_id, memory_type, pattern_signature)
        WHERE status NOT IN ('rejected', 'expired', 'superseded')
          AND visibility = 'tenant'
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS memory_events (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
            conversation_id UUID,
            run_id UUID,
            request_id UUID,
            agent_id UUID,
            workflow_id UUID,
            event_type VARCHAR(40) NOT NULL CHECK (event_type IN {_EVENTS}),
            source_component VARCHAR(80) NOT NULL DEFAULT '',
            phase VARCHAR(80) NOT NULL DEFAULT '',
            outcome VARCHAR(80) NOT NULL DEFAULT '',
            idempotency_key VARCHAR(200),
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_events_idem
        ON memory_events (organization_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_events_org_memory_time
        ON memory_events (organization_id, memory_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_events_org_run
        ON memory_events (organization_id, run_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_events_org_conversation
        ON memory_events (organization_id, conversation_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS memory_evidence (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            memory_id UUID NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL CHECK (kind IN {_KINDS}),
            ref_id UUID,
            ref_label VARCHAR(240) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memory_evidence_org_memory
        ON memory_evidence (organization_id, memory_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memory_evidence")
    op.execute("DROP TABLE IF EXISTS memory_events")
    op.execute("DROP TABLE IF EXISTS memory_records")

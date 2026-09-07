"""PHASE 23 — Zent Intelligence Layer: Answerability Engine.

Revision ID: 079
Revises: 078
"""
from __future__ import annotations

from alembic import op

revision: str = "079"
down_revision: str = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_definitions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            concept VARCHAR(160) NOT NULL,
            definition TEXT NOT NULL,
            expression TEXT,
            data_type VARCHAR(20) NOT NULL DEFAULT 'concept'
                CHECK (data_type IN ('metric', 'dimension', 'concept', 'status_value')),
            status VARCHAR(20) NOT NULL DEFAULT 'approved'
                CHECK (status IN ('draft', 'approved', 'deprecated')),
            authoritative_source_id VARCHAR(120),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, concept)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence_traces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            trace_id VARCHAR(64) NOT NULL UNIQUE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            query_id UUID,
            user_query TEXT NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'admin',
            understanding JSONB NOT NULL DEFAULT '{}'::jsonb,
            query_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            decision JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(40) NOT NULL,
            answer TEXT,
            method VARCHAR(20) NOT NULL DEFAULT 'rag',
            model VARCHAR(120),
            budget JSONB NOT NULL DEFAULT '{}'::jsonb,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_intelligence_traces_org_created "
        "ON intelligence_traces(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS context_gaps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            gap_type VARCHAR(30) NOT NULL
                CHECK (gap_type IN ('CONTEXT_MISSING', 'DATA_MISSING')),
            concept VARCHAR(160) NOT NULL,
            evidence_hints JSONB NOT NULL DEFAULT '[]'::jsonb,
            occurrences INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'resolved', 'acknowledged')),
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, gap_type, concept)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_context_gaps_org_status "
        "ON context_gaps(organization_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS context_gaps")
    op.execute("DROP TABLE IF EXISTS intelligence_traces")
    op.execute("DROP TABLE IF EXISTS business_definitions")

"""AI Observability Traces & Spans v2 — traces, spans, correlación.

Revision ID: 055
Revises: 054
Create Date: 2026-09-02
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS traces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            agent_id UUID,
            deployment_id UUID,
            run_id UUID,
            trace_id VARCHAR(64) NOT NULL UNIQUE,
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            model VARCHAR(120),
            input TEXT,
            output TEXT,
            error TEXT,
            total_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_tokens INT NOT NULL DEFAULT 0,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_traces_org_time "
        "ON traces(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_traces_agent_time "
        "ON traces(agent_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trace_spans (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            trace_id VARCHAR(64) NOT NULL,
            parent_span_id UUID,
            stage VARCHAR(30) NOT NULL,
            name VARCHAR(200) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'ok',
            started_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            tokens INT NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trace_spans_trace "
        "ON trace_spans(trace_id, started_ms)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_trace_spans_stage "
        "ON trace_spans(stage, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64)"
    )
    op.execute(
        "ALTER TABLE api_logs ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE api_logs DROP COLUMN IF EXISTS trace_id")
    op.execute("ALTER TABLE usage_events DROP COLUMN IF EXISTS trace_id")
    op.execute("DROP TABLE IF EXISTS trace_spans")
    op.execute("DROP TABLE IF EXISTS traces")

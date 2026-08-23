"""Usage & Cost Engine — eventos, precios, quotas y alertas.

Revision ID: 009
Revises: 008
Create Date: 2026-08-21

usage_events (idempotente por request_id), pricing_models, usage_quotas,
usage_alerts, y columnas de quota en plans.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_events (
            id BIGSERIAL PRIMARY KEY,
            request_id UUID NOT NULL,
            event_type VARCHAR(30) NOT NULL DEFAULT 'rag_query',
            organization_id UUID NOT NULL,
            user_id UUID,
            project_id UUID,
            agent_id UUID,
            api_key_id UUID,
            model VARCHAR(120),
            provider VARCHAR(60),
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            embedding_tokens INTEGER NOT NULL DEFAULT 0,
            retrieval_count INTEGER NOT NULL DEFAULT 0,
            reranking_count INTEGER NOT NULL DEFAULT 0,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL DEFAULT 'completed',
            estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            actual_cost DOUBLE PRECISION,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (request_id, event_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_org_time "
        "ON usage_events(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_org_agent "
        "ON usage_events(organization_id, agent_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_events_org_key "
        "ON usage_events(organization_id, api_key_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pricing_models (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(60) NOT NULL,
            model VARCHAR(120) NOT NULL,
            input_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            output_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            embedding_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (provider, model)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_quotas (
            organization_id UUID PRIMARY KEY,
            daily_requests BIGINT,
            daily_tokens BIGINT,
            daily_cost DOUBLE PRECISION,
            monthly_requests BIGINT,
            monthly_tokens BIGINT,
            monthly_cost DOUBLE PRECISION,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS usage_alerts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            quota_type VARCHAR(30) NOT NULL,
            threshold_pct INTEGER NOT NULL,
            usage_value DOUBLE PRECISION NOT NULL,
            limit_value DOUBLE PRECISION NOT NULL,
            alerted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            acknowledged_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_alerts_org "
        "ON usage_alerts(organization_id, alerted_at DESC)"
    )
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS tokens_per_month BIGINT")
    op.execute(
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS monthly_cost_limit DOUBLE PRECISION"
    )
    op.execute(
        """
        INSERT INTO pricing_models (provider, model, input_cost_per_1k, output_cost_per_1k, embedding_cost_per_1k)
        VALUES
            ('default', 'default', 0.00015, 0.00060, 0.00002),
            ('openai', 'gpt-4o-mini', 0.00015, 0.00060, 0.00002),
            ('openai', 'gpt-4o', 0.00250, 0.01000, 0.00002),
            ('openai', 'gpt-4.1-mini', 0.00040, 0.00160, 0.00002),
            ('openai', 'baai/bge-m3', 0.0, 0.0, 0.00002),
            ('cohere', 'rerank-v3.5', 0.0, 0.0, 0.00020)
        ON CONFLICT (provider, model) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_events")
    op.execute("DROP TABLE IF EXISTS pricing_models")
    op.execute("DROP TABLE IF EXISTS usage_quotas")
    op.execute("DROP TABLE IF EXISTS usage_alerts")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS tokens_per_month")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS monthly_cost_limit")

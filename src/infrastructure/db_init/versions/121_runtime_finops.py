"""Zent AI Runtime — provider cost history, wallets, efficiency weights.

Revision ID: 121
Revises: 120
"""

from __future__ import annotations

from alembic import op

revision: str = "121"
down_revision: str = "120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE pricing_models
            ADD COLUMN IF NOT EXISTS request_cost DOUBLE PRECISION NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE pricing_models
            ADD COLUMN IF NOT EXISTS cost_kind VARCHAR(20) NOT NULL DEFAULT 'provider'
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_cost_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(60) NOT NULL,
            model VARCHAR(120) NOT NULL,
            input_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            output_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            embedding_cost_per_1k DOUBLE PRECISION NOT NULL DEFAULT 0,
            request_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            cost_kind VARCHAR(20) NOT NULL DEFAULT 'provider',
            effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            effective_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_provider_cost_history_lookup
        ON provider_cost_history (provider, model, effective_from DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_wallets (
            organization_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            trial_credits DOUBLE PRECISION NOT NULL DEFAULT 0,
            promo_credits DOUBLE PRECISION NOT NULL DEFAULT 0,
            paid_credits DOUBLE PRECISION NOT NULL DEFAULT 0,
            used_credits DOUBLE PRECISION NOT NULL DEFAULT 0,
            trial_ends_at TIMESTAMPTZ,
            request_limit INTEGER,
            token_limit INTEGER,
            agent_run_limit INTEGER,
            workflow_run_limit INTEGER,
            storage_limit_bytes BIGINT,
            on_limit VARCHAR(20) NOT NULL DEFAULT 'block',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS efficiency_score_weights (
            id SMALLINT PRIMARY KEY DEFAULT 1,
            quality DOUBLE PRECISION NOT NULL DEFAULT 0.40,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0.25,
            latency DOUBLE PRECISION NOT NULL DEFAULT 0.20,
            fallback DOUBLE PRECISION NOT NULL DEFAULT 0.15,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO efficiency_score_weights (id) VALUES (1)
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO pricing_models (
            provider, model, input_cost_per_1k, output_cost_per_1k,
            embedding_cost_per_1k, request_cost, cost_kind
        )
        VALUES
            ('jev', 'jev-latest', 0, 0, 0, 0, 'provider'),
            ('novita', 'default', 0.00015, 0.00060, 0, 0, 'provider'),
            ('novita', 'small', 0.00010, 0.00040, 0, 0, 'provider'),
            ('embeddings', 'default', 0, 0, 0.00002, 0, 'provider'),
            ('reranker', 'default', 0, 0, 0.00020, 0, 'provider')
        ON CONFLICT (provider, model) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS efficiency_score_weights")
    op.execute("DROP TABLE IF EXISTS tenant_wallets")
    op.execute("DROP TABLE IF EXISTS provider_cost_history")

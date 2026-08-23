"""Billing Platform — planes enriquecidos, provider, eventos, invoices.

Revision ID: 010
Revises: 009
Create Date: 2026-08-21

Columnas de límites/overage en plans, columnas de provider en
subscriptions, estado suspended, billing_events (webhook idempotente),
invoices y payments.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for ddl in (
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS included_storage BIGINT",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_agents INTEGER",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_knowledge_bases INTEGER",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_connectors INTEGER",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_request_cost_per_1k DOUBLE PRECISION",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_token_cost_per_1k DOUBLE PRECISION",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_storage_cost_per_gb DOUBLE PRECISION",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_connector_monthly_cents DOUBLE PRECISION",
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_agent_monthly_cents DOUBLE PRECISION",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30) DEFAULT 'manual'",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_customer_id VARCHAR(200)",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_subscription_id VARCHAR(200)",
    ):
        op.execute(ddl)

    op.execute(
        "ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_status_check"
    )
    op.execute(
        "ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_status_check "
        "CHECK (status IN "
        "('trialing','active','past_due','canceled','expired','paused','suspended'))"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            provider VARCHAR(30) NOT NULL,
            event_id VARCHAR(200) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            organization_id UUID,
            payload JSONB NOT NULL DEFAULT '{}',
            processed_at TIMESTAMPTZ,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (provider, event_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS invoices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            provider VARCHAR(30) NOT NULL DEFAULT 'manual',
            provider_invoice_id VARCHAR(200),
            period_start TIMESTAMPTZ NOT NULL,
            period_end TIMESTAMPTZ NOT NULL,
            subtotal_cents BIGINT NOT NULL DEFAULT 0,
            overage_cents BIGINT NOT NULL DEFAULT 0,
            total_cents BIGINT NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            issued_at TIMESTAMPTZ,
            paid_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, period_start, period_end)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_invoices_org "
        "ON invoices(organization_id, period_start DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            provider VARCHAR(30) NOT NULL DEFAULT 'manual',
            provider_payment_id VARCHAR(200),
            invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
            amount_cents BIGINT NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'USD',
            status VARCHAR(20) NOT NULL DEFAULT 'succeeded',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (provider, provider_payment_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_payments_org "
        "ON payments(organization_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payments")
    op.execute("DROP TABLE IF EXISTS invoices")
    op.execute("DROP TABLE IF EXISTS billing_events")

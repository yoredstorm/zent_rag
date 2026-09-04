-- =============================================================================
-- Billing Platform — plans enriquecidos, provider, eventos, invoices, payments
-- =============================================================================
-- - plans: included/limits/overage por columna (NULL = sin límite/cargo)
-- - subscriptions: columnas de provider
-- - billing_events: eventos de webhook idempotentes (event_id UNIQUE)
-- - invoices / payments: facturación y pagos con ids de provider UNIQUE
-- =============================================================================

ALTER TABLE plans ADD COLUMN IF NOT EXISTS included_storage BIGINT;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_agents INTEGER;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_knowledge_bases INTEGER;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_connectors INTEGER;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_request_cost_per_1k DOUBLE PRECISION;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_token_cost_per_1k DOUBLE PRECISION;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_storage_cost_per_gb DOUBLE PRECISION;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_connector_monthly_cents DOUBLE PRECISION;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS overage_agent_monthly_cents DOUBLE PRECISION;

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30) DEFAULT 'manual';
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_customer_id VARCHAR(200);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS provider_subscription_id VARCHAR(200);

-- Estados: suspended reemplaza paused (paused queda como legado mapeable)
ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_status_check;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_status_check
    CHECK (status IN ('trialing','active','past_due','canceled','expired','paused','suspended'));

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
);

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
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, period_start, period_end)
);

CREATE INDEX IF NOT EXISTS idx_invoices_org ON invoices(organization_id, period_start DESC);

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
);

CREATE INDEX IF NOT EXISTS idx_payments_org ON payments(organization_id, created_at DESC);

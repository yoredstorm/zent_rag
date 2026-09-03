-- =============================================================================
-- PROMPT 35 — Tenant Self-Service Billing & Invoices v2 (espejo de 054)
-- =============================================================================

CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    provider VARCHAR(30),
    provider_invoice_id VARCHAR(120),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    subtotal_cents INT NOT NULL DEFAULT 0,
    overage_cents INT NOT NULL DEFAULT 0,
    total_cents INT NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    status VARCHAR(20) NOT NULL DEFAULT 'issued',
    issued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(40);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS tax_cents INT NOT NULL DEFAULT 0;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_intent_id VARCHAR(120);
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS billing_address JSONB NOT NULL DEFAULT '{}';
UPDATE invoices SET invoice_number = 'INV-' || substr(replace(id::text, '-', ''), 1, 8)
WHERE invoice_number IS NULL;
ALTER TABLE invoices ALTER COLUMN invoice_number SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS invoices_invoice_number_key ON invoices(invoice_number);
CREATE INDEX IF NOT EXISTS idx_invoices_org_period ON invoices(organization_id, period_start DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_org_period_unique ON invoices(organization_id, period_start, period_end);

CREATE TABLE IF NOT EXISTS invoice_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    kind VARCHAR(20) NOT NULL DEFAULT 'subscription',
    description VARCHAR(200) NOT NULL,
    quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
    unit_price_cents INT NOT NULL DEFAULT 0,
    amount_cents INT NOT NULL DEFAULT 0,
    meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS billing_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE,
    legal_name VARCHAR(200),
    tax_id VARCHAR(60),
    address_line1 VARCHAR(200),
    address_line2 VARCHAR(200),
    city VARCHAR(100),
    region VARCHAR(100),
    postal_code VARCHAR(30),
    country VARCHAR(60),
    default_payment_method VARCHAR(20) NOT NULL DEFAULT 'card',
    card_last4 VARCHAR(4),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payment_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    invoice_id UUID,
    event_type VARCHAR(60) NOT NULL,
    provider VARCHAR(30) NOT NULL DEFAULT 'stripe',
    provider_event_id VARCHAR(120) NOT NULL UNIQUE,
    amount_cents INT NOT NULL DEFAULT 0,
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    status VARCHAR(20) NOT NULL DEFAULT 'received',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_payment_events_org_time ON payment_events(organization_id, created_at DESC);
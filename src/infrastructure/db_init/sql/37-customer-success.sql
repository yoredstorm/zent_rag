-- =============================================================================
-- PROMPT 12 — Customer Success (espejo de la migración 034_customer_success.py)
-- =============================================================================

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS onboarding_step INT NOT NULL DEFAULT 0;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS onboarding_completed_at TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS branding JSONB NOT NULL DEFAULT '{}';
ALTER TABLE organization_invites ADD COLUMN IF NOT EXISTS email_sent BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE organization_invites ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20);

CREATE TABLE IF NOT EXISTS report_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    email VARCHAR(320) NOT NULL,
    frequency VARCHAR(20) NOT NULL DEFAULT 'monthly',
    next_send_at TIMESTAMPTZ NOT NULL,
    last_sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, email, frequency)
);
-- =============================================================================
-- Stripe Price IDs per plan/interval (no secrets; price_id is not a secret)
-- =============================================================================
CREATE TABLE IF NOT EXISTS plan_provider_prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    interval VARCHAR(10) NOT NULL CHECK (interval IN ('monthly', 'annual')),
    provider VARCHAR(30) NOT NULL,
    price_id VARCHAR(200) NOT NULL,
    UNIQUE (plan_id, interval, provider)
);

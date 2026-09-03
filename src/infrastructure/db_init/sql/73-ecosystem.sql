-- =============================================================================
-- PROMPT 48 — AI Agent Marketplace & Ecosystem v2 (067)
-- =============================================================================

CREATE TABLE IF NOT EXISTS public_listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_org_id UUID NOT NULL,
    name VARCHAR(150) NOT NULL,
    slug VARCHAR(80) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(40) NOT NULL DEFAULT 'general',
    tags JSONB NOT NULL DEFAULT '[]',
    pricing_type VARCHAR(15) NOT NULL DEFAULT 'free',
    price_cents INT NOT NULL DEFAULT 0,
    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    screenshot_urls JSONB NOT NULL DEFAULT '[]',
    version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    status VARCHAR(15) NOT NULL DEFAULT 'draft',
    installs INT NOT NULL DEFAULT 0,
    rating DOUBLE PRECISION NOT NULL DEFAULT 0,
    reviews_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_public_listings_catalog
    ON public_listings(status, category, rating DESC);

CREATE TABLE IF NOT EXISTS listing_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL,
    version VARCHAR(20) NOT NULL,
    changelog TEXT,
    config_template JSONB NOT NULL DEFAULT '{}',
    prompt_template TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_listing_versions_listing
    ON listing_versions(listing_id, version);

CREATE TABLE IF NOT EXISTS listing_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    verified BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (listing_id, organization_id)
);

CREATE TABLE IF NOT EXISTS marketplace_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    price_cents INT NOT NULL DEFAULT 0,
    commission_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
    platform_fee_cents INT NOT NULL DEFAULT 0,
    publisher_payout_cents INT NOT NULL DEFAULT 0,
    status VARCHAR(15) NOT NULL DEFAULT 'paid',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_marketplace_orders_org
    ON marketplace_orders(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    publisher_org_id UUID NOT NULL,
    amount_cents INT NOT NULL DEFAULT 0,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    status VARCHAR(15) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    paid_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_payouts_publisher
    ON payouts(publisher_org_id, period_end DESC);

CREATE TABLE IF NOT EXISTS partner_programs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE,
    level VARCHAR(15) NOT NULL DEFAULT 'builder',
    badge VARCHAR(40) NOT NULL DEFAULT 'builder',
    status VARCHAR(15) NOT NULL DEFAULT 'active',
    earned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
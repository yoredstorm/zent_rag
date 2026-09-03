-- =============================================================================
-- PROMPT 18 — Model Gateway (espejo de la migración 039_model_gateway.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    condition_type VARCHAR(20) NOT NULL DEFAULT 'default',
    condition_value DOUBLE PRECISION,
    model VARCHAR(120) NOT NULL,
    traffic_pct INT NOT NULL DEFAULT 100,
    priority INT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_model_routes_org ON model_routes(organization_id, active, priority);

CREATE TABLE IF NOT EXISTS model_budgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    model VARCHAR(120) NOT NULL,
    monthly_budget_cents INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, model)
);

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS routing JSONB;
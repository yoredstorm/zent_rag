-- =============================================================================
-- PROMPT 29 — Cost Governance & FinOps v2 (espejo de 048_cost_governance.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS cost_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    key VARCHAR(60) NOT NULL,
    value VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, key, value)
);

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS cost_tags JSONB NOT NULL DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_usage_events_cost_tags ON usage_events USING GIN (cost_tags);

CREATE TABLE IF NOT EXISTS cost_alert_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    category VARCHAR(40) NOT NULL DEFAULT 'total',
    dimension VARCHAR(120),
    threshold_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
    adaptive BOOLEAN NOT NULL DEFAULT true,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cost_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    rule_id UUID,
    category VARCHAR(40) NOT NULL DEFAULT 'total',
    dimension VARCHAR(120),
    baseline_daily_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    today_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    threshold_pct DOUBLE PRECISION NOT NULL DEFAULT 20,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (rule_id, triggered_at)
);
CREATE INDEX IF NOT EXISTS idx_cost_alerts_org_time ON cost_alerts(organization_id, triggered_at DESC);

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cost_team VARCHAR(120);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS cost_business_unit VARCHAR(120);
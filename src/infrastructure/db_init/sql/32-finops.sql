-- =============================================================================
-- PROMPT 07 — FinOps (espejo de la migración 029_finops.py)
-- =============================================================================

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS deployment_id UUID
    REFERENCES deployments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_usage_events_deployment ON usage_events(deployment_id);

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS finops_budget_cents BIGINT;

CREATE TABLE IF NOT EXISTS finops_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    alert_type VARCHAR(40) NOT NULL,
    message TEXT NOT NULL,
    threshold_value DOUBLE PRECISION,
    actual_value DOUBLE PRECISION,
    acknowledged BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_finops_alerts_org ON finops_alerts(organization_id, created_at DESC);
-- =============================================================================
-- PROMPT 14 — Optimizer (espejo de la migración 036_optimizer.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS optimizer_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID,
    deployment_id UUID,
    recommendation_key VARCHAR(60) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'info',
    message TEXT NOT NULL,
    expected_savings_pct DOUBLE PRECISION,
    status VARCHAR(20) NOT NULL DEFAULT 'suggested',
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_optimizer_org ON optimizer_actions(organization_id, status, created_at DESC);
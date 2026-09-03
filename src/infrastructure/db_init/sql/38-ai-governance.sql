-- =============================================================================
-- PROMPT 13 — AI Governance (espejo de la migración 035_ai_governance.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS anomaly_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,
    anomaly_type VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    acknowledged_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_anomaly_events_type ON anomaly_events(anomaly_type, created_at DESC);

CREATE TABLE IF NOT EXISTS prompt_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key VARCHAR(120) NOT NULL,
    organization_id UUID NOT NULL,
    version INT NOT NULL,
    content TEXT NOT NULL,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prompt_revisions_key ON prompt_revisions(prompt_key, organization_id, version DESC);

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ai_pii_masking_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ai_guardrails JSONB NOT NULL DEFAULT '{}';
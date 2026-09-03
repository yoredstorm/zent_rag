-- =============================================================================
-- PROMPT 08 — Observability (espejo de la migración 030_observability.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_name VARCHAR(80) PRIMARY KEY,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS incident_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    deployment_id UUID,
    alert_type VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    threshold_value DOUBLE PRECISION,
    actual_value DOUBLE PRECISION,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    webhook_status VARCHAR(20),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_incident_alerts_org ON incident_alerts(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_incident_alerts_status ON incident_alerts(status, created_at DESC);

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ops_webhook_url VARCHAR(500);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ops_webhook_enabled BOOLEAN NOT NULL DEFAULT false;
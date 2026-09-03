-- =============================================================================
-- Public API — api_logs + hardening de API keys (ip allowlist, rate limit)
-- Espejo SQL de la migración alembic 028_public_api (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS api_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    deployment_id UUID,
    agent_id UUID,
    request_id UUID NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status INTEGER NOT NULL,
    latency_ms DOUBLE PRECISION,
    tokens INTEGER NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION,
    api_key_id UUID,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_api_logs_org
    ON api_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_logs_deployment
    ON api_logs(deployment_id, created_at DESC);

ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS ip_allowlist JSONB
    NOT NULL DEFAULT '[]';
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS rate_limit_per_minute INTEGER;
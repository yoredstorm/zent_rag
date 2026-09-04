-- =============================================================================
-- PROMPT 49 — AI Security Operations Center (SOC) v2 (068)
-- =============================================================================

CREATE TABLE IF NOT EXISTS security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    severity VARCHAR(15) NOT NULL DEFAULT 'low',
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'detected',
    evidence JSONB NOT NULL DEFAULT '{}',
    timeline JSONB NOT NULL DEFAULT '[]',
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_security_events_org
    ON security_events(organization_id, status, score DESC);

CREATE TABLE IF NOT EXISTS security_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL,
    action_type VARCHAR(20) NOT NULL,
    target VARCHAR(120),
    status VARCHAR(15) NOT NULL DEFAULT 'executed',
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_security_responses_event
    ON security_responses(event_id, created_at);

CREATE TABLE IF NOT EXISTS security_posture_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    date DATE NOT NULL,
    threat_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    open_events INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, date)
);

-- Respuestas automáticas:
ALTER TABLE deployments DROP CONSTRAINT IF EXISTS deployments_status_check;
ALTER TABLE deployments ADD CONSTRAINT deployments_status_check CHECK
    (status IN ('pending', 'deploying', 'healthy', 'degraded', 'failed',
     'rolled_back', 'blocked'));
ALTER TABLE rate_limit_rules
    ADD COLUMN IF NOT EXISTS throttle_factor DOUBLE PRECISION NOT NULL DEFAULT 1.0;
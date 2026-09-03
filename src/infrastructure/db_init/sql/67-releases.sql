-- =============================================================================
-- PROMPT 42 — AI Agent Versioning & Rollout v2 (espejo de 061_rollout.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL,
    version_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL DEFAULT 'canary',
    traffic_pct INT NOT NULL DEFAULT 100,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    health_score DOUBLE PRECISION,
    promoted_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_releases_agent
    ON agent_releases(agent_id, channel, created_at DESC);

CREATE TABLE IF NOT EXISTS release_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id UUID NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_release_events_release
    ON release_events(release_id, created_at);
-- =============================================================================
-- Agent Runs — execution traces del Agent Runtime
-- =============================================================================
-- Cada run guarda pasos (plan, tool calls, final), latencias, tokens y
-- costo. NUNCA secrets ni outputs completos (el runtime trunca).
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    user_id UUID,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    status VARCHAR(30) NOT NULL,
    message TEXT NOT NULL,
    answer TEXT,
    steps JSONB NOT NULL DEFAULT '[]',
    total_latency_ms DOUBLE PRECISION DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost DOUBLE PRECISION DEFAULT 0,
    injection_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_org
    ON agent_runs(organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent
    ON agent_runs(agent_id, created_at DESC);

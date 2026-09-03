-- =============================================================================
-- PROMPT 36 — AI Observability Traces & Spans v2 (espejo de 055_traces.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID,
    deployment_id UUID,
    run_id UUID,
    trace_id VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    model VARCHAR(120),
    input TEXT,
    output TEXT,
    error TEXT,
    total_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_traces_org_time ON traces(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_traces_agent_time ON traces(agent_id, created_at DESC);

CREATE TABLE IF NOT EXISTS trace_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id VARCHAR(64) NOT NULL,
    parent_span_id UUID,
    stage VARCHAR(30) NOT NULL,
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ok',
    started_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    tokens INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_trace_spans_trace ON trace_spans(trace_id, started_ms);
CREATE INDEX IF NOT EXISTS idx_trace_spans_stage ON trace_spans(stage, created_at DESC);

ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64);
ALTER TABLE api_logs ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64);
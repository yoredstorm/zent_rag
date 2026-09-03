-- =============================================================================
-- PROMPT 40 — Sentiment & Feedback Analytics (espejo de 059_feedback.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID,
    deployment_id UUID,
    run_id UUID,
    trace_id VARCHAR(64),
    rating VARCHAR(10) NOT NULL,
    reason VARCHAR(40),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_feedback_org_time ON feedback(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_agent_time ON feedback(agent_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_run ON feedback(run_id) WHERE run_id IS NOT NULL;
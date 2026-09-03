-- =============================================================================
-- PROMPT 39 — Tenant Onboarding Experience v2 (espejo de 058)
-- =============================================================================

CREATE TABLE IF NOT EXISTS onboarding_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE,
    steps JSONB NOT NULL DEFAULT '{}',
    current_step VARCHAR(40) NOT NULL DEFAULT 'create_kb',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    time_to_first_value_seconds DOUBLE PRECISION,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS onboarding_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    step VARCHAR(40) NOT NULL,
    event_type VARCHAR(20) NOT NULL DEFAULT 'step_done',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_events_step ON onboarding_events(step, event_type, created_at);
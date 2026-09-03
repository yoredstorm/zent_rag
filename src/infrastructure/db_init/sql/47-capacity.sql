-- =============================================================================
-- PROMPT 22 — Capacity Planning (espejo de la migración 041_capacity.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS scaling_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue VARCHAR(60) NOT NULL,
    action VARCHAR(20) NOT NULL,
    worker_count_target INT,
    depth INT,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_scaling_events_created ON scaling_events(created_at DESC);
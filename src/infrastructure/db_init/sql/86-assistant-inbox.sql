-- =============================================================================
-- Living Assistants UX — inbox (espejo de 114_assistant_inbox.py).
-- "Marcar resuelto" sobre business_results.
-- =============================================================================

ALTER TABLE business_results ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS acknowledged_by UUID;

CREATE INDEX IF NOT EXISTS idx_business_results_inbox
    ON business_results(organization_id, acknowledged_at, generated_at DESC);

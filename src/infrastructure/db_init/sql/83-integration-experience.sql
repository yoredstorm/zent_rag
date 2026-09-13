-- =============================================================================
-- Integration Experience — manifest v2 (events column)
-- (espejo de 111_demo_integrations.py). Las recetas demo se siembran
-- idempotentemente desde src/platform/marketplace/demo_integrations.py.
-- =============================================================================

ALTER TABLE integration_manifests ADD COLUMN IF NOT EXISTS events
    JSONB NOT NULL DEFAULT '[]'::jsonb;

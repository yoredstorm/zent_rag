-- =============================================================================
-- PHASE 31B — Semantic Mapping Studio
-- =============================================================================

ALTER TABLE catalog_fields
    ADD COLUMN IF NOT EXISTS role VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS mapping_type VARCHAR(40) NOT NULL DEFAULT 'DIRECT',
    ADD COLUMN IF NOT EXISTS unit VARCHAR(40),
    ADD COLUMN IF NOT EXISTS currency VARCHAR(12),
    ADD COLUMN IF NOT EXISTS grain VARCHAR(40),
    ADD COLUMN IF NOT EXISTS aggregation_behavior VARCHAR(40),
    ADD COLUMN IF NOT EXISTS synonyms JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS signal_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ;

ALTER TABLE catalog_relationships
    ADD COLUMN IF NOT EXISTS business_from VARCHAR(160),
    ADD COLUMN IF NOT EXISTS business_to VARCHAR(160),
    ADD COLUMN IF NOT EXISTS business_verb VARCHAR(40);

CREATE TABLE IF NOT EXISTS catalog_abbrev_lexicon (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    token VARCHAR(80) NOT NULL,
    meaning VARCHAR(160) NOT NULL,
    role VARCHAR(40) NOT NULL DEFAULT 'UNKNOWN',
    status VARCHAR(20) NOT NULL DEFAULT 'signal',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, token, meaning)
);
CREATE INDEX IF NOT EXISTS idx_catalog_lexicon_org
    ON catalog_abbrev_lexicon(organization_id, token);

CREATE TABLE IF NOT EXISTS catalog_mapping_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    field_id UUID,
    column_id UUID,
    old_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    new_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    source VARCHAR(40) NOT NULL DEFAULT 'studio',
    version INT NOT NULL DEFAULT 1,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_catalog_mapping_versions_org
    ON catalog_mapping_versions(organization_id, field_id, created_at DESC);

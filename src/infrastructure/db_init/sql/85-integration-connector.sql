-- =============================================================================
-- Integration Experience II — Universal API Connector
-- (espejo de 113_integration_connector.py). Los borradores se crean al
-- importar un documento OpenAPI y se instalan tras la revisión humana.
-- =============================================================================

ALTER TABLE integration_manifests ADD COLUMN IF NOT EXISTS organization_id UUID;

CREATE INDEX IF NOT EXISTS idx_integration_manifests_org
    ON integration_manifests(organization_id);

CREATE TABLE IF NOT EXISTS integration_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
    slug VARCHAR(80) NOT NULL,
    name VARCHAR(150) NOT NULL,
    source_kind VARCHAR(20) NOT NULL DEFAULT 'url',
    source_url TEXT,
    spec_hash VARCHAR(64),
    openapi_version VARCHAR(20),
    base_url TEXT,
    auth_mode VARCHAR(30) NOT NULL DEFAULT 'none',
    draft JSONB NOT NULL DEFAULT '{}',
    report JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    integration_slug VARCHAR(80),
    install_id UUID,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_integration_drafts_org
    ON integration_drafts(organization_id, status);

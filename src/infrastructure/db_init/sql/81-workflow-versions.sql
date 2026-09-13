-- =============================================================================
-- Workflow Studio — versiones publicables (espejo de 109_workflow_versions.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS workflow_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workflow_id UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'production', 'archived')),
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_workflow_versions_wf
    ON workflow_versions(workflow_id, version_number DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_versions_org
    ON workflow_versions(organization_id);

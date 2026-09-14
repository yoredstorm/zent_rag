-- =============================================================================
-- Workflow Studio UX v2 — ejecución parcial + pinned test data
-- (espejo de 112_studio_debug.py)
-- =============================================================================

ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS run_mode VARCHAR(20) NOT NULL DEFAULT 'full',
    ADD COLUMN IF NOT EXISTS target_node_id VARCHAR(80),
    ADD COLUMN IF NOT EXISTS source_run_id UUID;

CREATE TABLE IF NOT EXISTS workflow_pinned_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workflow_id UUID NOT NULL,
    node_id VARCHAR(80) NOT NULL,
    output JSONB NOT NULL DEFAULT '{}',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, node_id)
);
CREATE INDEX IF NOT EXISTS idx_workflow_pinned_org
    ON workflow_pinned_data(organization_id, workflow_id);

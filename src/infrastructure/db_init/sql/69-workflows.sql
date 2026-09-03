-- =============================================================================
-- PROMPT 44 — AI Workflow Automation Studio v2 (espejo de 063_workflows.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'webhook',
    trigger_config JSONB NOT NULL DEFAULT '{}',
    steps JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_workflows_org
    ON workflows(organization_id, created_at DESC);

-- workflow_runs / workflow_run_steps pre-existieron en la fase v1:
-- la fase v2 los amplió con ALTER TABLE (trigger_payload, duration_ms,
-- input, output, error, retries, duration_ms).
CREATE TABLE IF NOT EXISTS workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID NOT NULL,
    organization_id UUID,
    trigger VARCHAR(20) NOT NULL DEFAULT 'manual',
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    current_step INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_by UUID,
    trigger_payload JSONB NOT NULL DEFAULT '{}',
    duration_ms INT
);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_wf
    ON workflow_runs(workflow_id, started_at DESC);

CREATE TABLE IF NOT EXISTS workflow_run_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    step_index INT,
    step_type VARCHAR(20) NOT NULL DEFAULT 'llm',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    details JSONB,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    retries INT NOT NULL DEFAULT 0,
    duration_ms INT
);
CREATE INDEX IF NOT EXISTS idx_workflow_run_steps_run
    ON workflow_run_steps(run_id, step_index);

CREATE TABLE IF NOT EXISTS workflow_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(80) NOT NULL UNIQUE,
    name VARCHAR(150) NOT NULL,
    description TEXT,
    category VARCHAR(40) NOT NULL DEFAULT 'general',
    trigger_type VARCHAR(20) NOT NULL DEFAULT 'webhook',
    steps JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed de 4 plantillas (kb-digest, lead-alert, incident-escalate,
-- daily-report) — ver 063_workflows.py para el texto completo.
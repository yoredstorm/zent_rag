-- =============================================================================
-- PROMPT 25 — AI Quality & Evals v2 (espejo de la migración 044_evals_v2.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS eval_v2_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    version INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_v2_datasets_org ON eval_v2_datasets(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_v2_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id UUID NOT NULL,
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    context TEXT,
    score_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_v2_items_dataset ON eval_v2_items(dataset_id);

CREATE TABLE IF NOT EXISTS eval_v2_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    dataset_version INT NOT NULL,
    agent_id UUID NOT NULL,
    agent_version_id UUID,
    model VARCHAR(120),
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    score_overall DOUBLE PRECISION,
    faithfulness DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    latency_p95 DOUBLE PRECISION,
    cost_total DOUBLE PRECISION,
    passed_gate BOOLEAN,
    regression BOOLEAN NOT NULL DEFAULT false,
    created_by UUID,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_eval_v2_runs_org ON eval_v2_runs(organization_id, started_at DESC);

CREATE TABLE IF NOT EXISTS eval_v2_run_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    item_id UUID,
    question TEXT NOT NULL,
    answer TEXT,
    expected_answer TEXT NOT NULL,
    score DOUBLE PRECISION,
    faithfulness DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    latency_ms DOUBLE PRECISION,
    cost DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_eval_v2_run_items_run ON eval_v2_run_items(run_id);
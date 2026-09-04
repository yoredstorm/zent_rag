-- =============================================================================
-- Evaluation Engine — datasets, runs y resultados por caso
-- Espejo SQL de la migración alembic 011_evaluation_engine (bases nuevas).
-- Debe correr antes de 29-eval-examples.sql (FK eval_examples.dataset_id).
-- =============================================================================

CREATE TABLE IF NOT EXISTS eval_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 2,
    cases JSONB NOT NULL DEFAULT '[]',
    weights JSONB NOT NULL DEFAULT '{}',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_datasets_org
    ON eval_datasets(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    dataset_id UUID,
    dataset_name TEXT,
    target_type VARCHAR(10) NOT NULL,
    target_id UUID,
    target_name TEXT,
    version_snapshot JSONB NOT NULL DEFAULT '{}',
    version_id TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    summary JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_org
    ON eval_runs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_eval_runs_version
    ON eval_runs(version_id, created_at DESC);

CREATE TABLE IF NOT EXISTS eval_case_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    question TEXT,
    answer TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    target JSONB NOT NULL DEFAULT '{}',
    metrics JSONB NOT NULL DEFAULT '{}',
    scores JSONB NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_eval_cases_run
    ON eval_case_results(run_id, created_at);

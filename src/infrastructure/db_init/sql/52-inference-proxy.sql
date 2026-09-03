-- =============================================================================
-- PROMPT 27 — Multitenant LLM Proxy (espejo de 046_inference_proxy.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS inference_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name VARCHAR(120) NOT NULL UNIQUE,
    backend VARCHAR(20) NOT NULL DEFAULT 'openai',
    capacity INT NOT NULL DEFAULT 50,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO inference_models (model_name, backend, capacity) VALUES
('gpt-4o-mini', 'openai', 50),
('gpt-4o', 'openai', 10),
('zent-cheap', 'vllm', 100),
('zent-fast', 'tgi', 200)
ON CONFLICT (model_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS inference_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    deployment_id UUID,
    agent_id UUID,
    model VARCHAR(120) NOT NULL,
    backend VARCHAR(20),
    status VARCHAR(20) NOT NULL DEFAULT 'completed',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    queue_wait_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_inference_logs_org_time ON inference_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inference_logs_model_time ON inference_logs(model, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_inference_logs_dep_time ON inference_logs(deployment_id, created_at DESC);

ALTER TABLE rate_limit_rules ADD COLUMN IF NOT EXISTS deployment_id UUID;
-- =============================================================================
-- PROMPT 26 — Usage Metering & Rate Limits v2 (espejo de 045_metering.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS rate_limit_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_name VARCHAR(50),
    endpoint_prefix VARCHAR(120) NOT NULL DEFAULT '/',
    limit_per_minute INT NOT NULL DEFAULT 30,
    burst INT NOT NULL DEFAULT 10,
    enabled BOOLEAN NOT NULL DEFAULT true,
    priority INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_rules_plan ON rate_limit_rules(plan_name, endpoint_prefix);

INSERT INTO rate_limit_rules (plan_name, endpoint_prefix, limit_per_minute, burst, priority) VALUES
('trial', '/', 30, 10, 10),
('starter', '/', 60, 15, 10),
('pro', '/', 100, 25, 10),
('enterprise', '/', 500, 100, 10),
(NULL, '/api/v1/rag/query', 60, 15, 20),
(NULL, '/api/v1/deployments', 200, 50, 20)
ON CONFLICT DO NOTHING;
-- =============================================================================
-- PROMPT 47 — AI Risk & Compliance Center v2 (066)
-- =============================================================================

CREATE TABLE IF NOT EXISTS ai_risks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID,
    risk_type VARCHAR(30) NOT NULL,
    severity VARCHAR(15) NOT NULL DEFAULT 'low',
    likelihood DOUBLE PRECISION NOT NULL DEFAULT 0,
    impact DOUBLE PRECISION NOT NULL DEFAULT 0,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(15) NOT NULL DEFAULT 'open',
    source VARCHAR(10) NOT NULL DEFAULT 'auto',
    evidence JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    mitigated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ai_risks_org
    ON ai_risks(organization_id, status, score DESC);

CREATE TABLE IF NOT EXISTS risk_mitigations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    risk_id UUID NOT NULL,
    action_type VARCHAR(20) NOT NULL DEFAULT 'mitigation',
    description TEXT,
    performed_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS compliance_posture_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    date DATE NOT NULL,
    framework VARCHAR(20) NOT NULL,
    score DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, date, framework)
);

-- Vincula controles a tipos de riesgo + framework eu_ai_act (8 seeds
-- EUAI-01..08) — ver 066_risk_compliance.py para el texto completo.
ALTER TABLE compliance_controls
    ADD COLUMN IF NOT EXISTS risk_type VARCHAR(30);
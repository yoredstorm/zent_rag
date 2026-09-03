-- =============================================================================
-- PROMPT 20 — Security Center (espejo de la migración 040_security_center.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS security_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID,
    finding_type VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    target_type VARCHAR(40) NOT NULL,
    target_id VARCHAR(80),
    detail TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_security_findings_org ON security_findings(organization_id, status, created_at DESC);
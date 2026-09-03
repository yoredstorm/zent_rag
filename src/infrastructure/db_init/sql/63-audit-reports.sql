-- =============================================================================
-- PROMPT 38 — Tenant Audit & Compliance Reports v2 (espejo de 057)
-- =============================================================================

CREATE TABLE IF NOT EXISTS audit_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    report_type VARCHAR(30) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    format VARCHAR(10) NOT NULL DEFAULT 'csv',
    file_key VARCHAR(300) NOT NULL,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    integrity_hash VARCHAR(64) NOT NULL,
    prev_hash VARCHAR(64),
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + interval '90 days'
);
CREATE INDEX IF NOT EXISTS idx_audit_reports_org_time ON audit_reports(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS compliance_controls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    framework VARCHAR(30) NOT NULL,
    control_id VARCHAR(40) NOT NULL,
    title VARCHAR(200) NOT NULL,
    category VARCHAR(60) NOT NULL DEFAULT 'general',
    required_evidence VARCHAR(120),
    enabled BOOLEAN NOT NULL DEFAULT true,
    UNIQUE (framework, control_id)
);
-- 24 controles: SOC2 (CC2.1, CC6.1, CC7.2, CC8.1, A1.2, A1.3, C1.1, C1.2),
-- GDPR (A.5, A.7, A.15, A.16, A.17, A.24, A.32, A.33),
-- ISO27001 (A.5.1, A.6.1, A.8.2, A.9.1, A.12.4, A.13.1, A.16.1, A.18.1)

CREATE TABLE IF NOT EXISTS compliance_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    framework VARCHAR(30) NOT NULL,
    control_id VARCHAR(40) NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'review',
    evidence TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, framework, control_id)
);
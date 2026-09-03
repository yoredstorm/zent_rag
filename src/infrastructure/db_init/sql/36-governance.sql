-- =============================================================================
-- PROMPT 11 — Governance (espejo de la migración 033_governance.py)
-- =============================================================================

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS retention_days INT NOT NULL DEFAULT 365;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS data_residency_region VARCHAR(40);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dsr_contact_email VARCHAR(320);

CREATE TABLE IF NOT EXISTS compliance_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    actor_user_id UUID,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_compliance_org ON compliance_events(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS kms_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    key_version INT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    dek_enc VARCHAR(600) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rotated_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ,
    UNIQUE (key_version)
);
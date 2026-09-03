-- =============================================================================
-- PROMPT 09 — Enterprise (espejo de la migración 031_enterprise.py)
-- =============================================================================

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS key_max_age_days INT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS scim_token_hash VARCHAR(64);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_enabled BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_issuer VARCHAR(300);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_client_id VARCHAR(200);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_client_secret_enc VARCHAR(600);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS sso_oidc_roles_claim VARCHAR(50) DEFAULT 'roles';

CREATE TABLE IF NOT EXISTS scim_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    role_name VARCHAR(50) NOT NULL DEFAULT 'member',
    members JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, display_name)
);
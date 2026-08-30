-- =============================================================================
-- Organization invites — pending membership invitations (no mailer)
-- =============================================================================
CREATE TABLE IF NOT EXISTS organization_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email VARCHAR(320) NOT NULL,
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_org_invites_org_email
    ON organization_invites (organization_id, email);

CREATE INDEX IF NOT EXISTS idx_org_invites_token_hash
    ON organization_invites (token_hash);

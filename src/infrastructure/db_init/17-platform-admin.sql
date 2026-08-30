-- =============================================================================
-- Platform admin identity — Control Center (typ=platform sessions)
-- =============================================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE users ALTER COLUMN organization_id DROP NOT NULL;

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_platform_admin_org_chk;
ALTER TABLE users ADD CONSTRAINT users_platform_admin_org_chk
    CHECK (
        (is_platform_admin = true AND organization_id IS NULL)
        OR (is_platform_admin = false AND organization_id IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS idx_users_platform_admin
    ON users (is_platform_admin)
    WHERE is_platform_admin = true;

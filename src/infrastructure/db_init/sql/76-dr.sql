-- =============================================================================
-- PROMPT 51 — AI Disaster Recovery & High Availability v2 (070)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dr_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(150) NOT NULL,
    scope VARCHAR(20) NOT NULL DEFAULT 'agent',
    target_id UUID,
    rpo_minutes INT NOT NULL DEFAULT 60,
    rto_minutes INT NOT NULL DEFAULT 15,
    replication_region VARCHAR(40) NOT NULL DEFAULT 'eu-west-1',
    status VARCHAR(15) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dr_policies_org
    ON dr_policies(organization_id, status);

CREATE TABLE IF NOT EXISTS dr_drills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    policy_id UUID NOT NULL,
    region VARCHAR(40) NOT NULL,
    status VARCHAR(15) NOT NULL DEFAULT 'running',
    failover_ok BOOLEAN,
    recovery_validated BOOLEAN,
    duration_ms INT,
    detail TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_dr_drills_org
    ON dr_drills(organization_id, started_at DESC);

-- dr_backups pre-existió en la fase v1 (backups Qdrant) — ampliado a v2:
CREATE TABLE IF NOT EXISTS dr_backups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    kind VARCHAR(30),
    status VARCHAR(15) NOT NULL DEFAULT 'completed',
    trigger VARCHAR(20),
    file_path TEXT,
    size_bytes BIGINT,
    checksum_sha256 VARCHAR(64),
    duration_ms INT,
    qdrant_snapshot BOOLEAN,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    scope VARCHAR(20) NOT NULL DEFAULT 'agent',
    source_id UUID,
    version INT NOT NULL DEFAULT 1,
    artifact JSONB NOT NULL DEFAULT '{}',
    restored_at TIMESTAMPTZ,
    restored_to_region VARCHAR(40)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_dr_backups_version
    ON dr_backups(organization_id, scope, source_id, version);
CREATE INDEX IF NOT EXISTS idx_dr_backups_org
    ON dr_backups(organization_id, scope, source_id, created_at DESC);
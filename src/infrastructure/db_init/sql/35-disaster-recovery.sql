-- =============================================================================
-- PROMPT 10 — Disaster Recovery (espejo de la migración 032_disaster_recovery.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dr_regions (
    code VARCHAR(40) PRIMARY KEY,
    name VARCHAR(120) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true
);
INSERT INTO dr_regions (code, name) VALUES
('us-east-1', 'US East (N. Virginia)'),
('eu-west-1', 'EU West (Ireland)'),
('ap-southeast-1', 'Asia Pacific (Singapore)'),
('local', 'Local / On-prem')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS dr_backups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    kind VARCHAR(20) NOT NULL DEFAULT 'full',
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    trigger VARCHAR(20) NOT NULL DEFAULT 'manual',
    file_path TEXT,
    size_bytes BIGINT,
    checksum_sha256 VARCHAR(64),
    duration_ms INT,
    qdrant_snapshot BOOLEAN NOT NULL DEFAULT false,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_dr_backups_org ON dr_backups(organization_id, created_at DESC);

ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_regions JSONB NOT NULL DEFAULT '[]';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_rpo_minutes INT NOT NULL DEFAULT 1440;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS dr_backup_enabled BOOLEAN NOT NULL DEFAULT false;
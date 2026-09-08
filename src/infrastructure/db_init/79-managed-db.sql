-- PHASE 31C — Managed customer databases (data plane)

CREATE TABLE IF NOT EXISTS managed_databases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    provider VARCHAR(40) NOT NULL DEFAULT 'local',
    db_name VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    size_quota_mb INT NOT NULL DEFAULT 256,
    connector_id UUID,
    backup_retention_days INT NOT NULL DEFAULT 0,
    last_backup_at TIMESTAMPTZ,
    restore_ready BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS managed_schema_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    managed_database_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'DRAFT',
    prompt TEXT,
    proposal_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    ddl_preview TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

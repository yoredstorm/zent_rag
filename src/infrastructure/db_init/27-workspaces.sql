-- =============================================================================
-- Workspaces — Tenant → Workspace → {Agents, Knowledge Bases, Connectors}
-- Espejo SQL de la migración alembic 024_workspaces (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(64) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_workspaces_org ON workspaces(organization_id);

ALTER TABLE agents ADD COLUMN IF NOT EXISTS workspace_id UUID
    REFERENCES workspaces(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_agents_workspace ON agents(organization_id, workspace_id);

ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS workspace_id UUID
    REFERENCES workspaces(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_knowledge_bases_workspace
    ON knowledge_bases(organization_id, workspace_id);

ALTER TABLE connectors ADD COLUMN IF NOT EXISTS workspace_id UUID
    REFERENCES workspaces(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_connectors_workspace
    ON connectors(organization_id, workspace_id);

ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check;

UPDATE agents SET status = CASE WHEN is_active THEN 'ready' ELSE 'archived' END
WHERE status IN ('active', 'archived');

ALTER TABLE agents ADD CONSTRAINT agents_status_check
    CHECK (status IN ('draft', 'configured', 'evaluating', 'ready',
                      'deployed', 'archived'));
ALTER TABLE agents ALTER COLUMN status SET DEFAULT 'draft';

INSERT INTO permissions (id, code, description) VALUES
    ('40000000-0000-0000-0000-000000000046', 'workspaces:read',
     'Ver workspaces de la organización'),
    ('40000000-0000-0000-0000-000000000047', 'workspaces:write',
     'Crear/editar/archivar workspaces')
ON CONFLICT (code) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
WHERE r.organization_id IS NULL AND r.name IN ('owner', 'admin', 'member')
ON CONFLICT DO NOTHING;
-- =============================================================================
-- PHASE 31C — Workspace isolation (demo vs business)
-- =============================================================================
-- Idempotente. catalog_sources puede no existir aún en initdb (Alembic 080).

ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'business';

ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_kind_check;
ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_kind_check
    CHECK (kind IN ('demo', 'business'));

ALTER TABLE memberships
    ADD COLUMN IF NOT EXISTS active_workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_memberships_active_workspace
    ON memberships(active_workspace_id);

ALTER TABLE kb_sources
    ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_kb_sources_workspace
    ON kb_sources(organization_id, workspace_id);

DO $$
BEGIN
    IF to_regclass('public.catalog_sources') IS NOT NULL THEN
        ALTER TABLE catalog_sources ADD COLUMN IF NOT EXISTS workspace_id UUID;
        CREATE INDEX IF NOT EXISTS idx_catalog_sources_workspace
            ON catalog_sources(organization_id, workspace_id);
        UPDATE catalog_sources cs
        SET workspace_id = w.id
        FROM workspaces w
        WHERE cs.workspace_id IS NULL
          AND w.organization_id = cs.organization_id
          AND w.slug = 'default';
    END IF;
END $$;

UPDATE kb_sources ks
SET workspace_id = w.id
FROM workspaces w
WHERE ks.workspace_id IS NULL
  AND w.organization_id = ks.organization_id
  AND w.slug = 'default';

UPDATE connectors c
SET workspace_id = w.id
FROM workspaces w
WHERE c.workspace_id IS NULL
  AND c.organization_id = w.organization_id
  AND w.slug = 'default';

UPDATE knowledge_bases k
SET workspace_id = w.id
FROM workspaces w
WHERE k.workspace_id IS NULL
  AND k.organization_id = w.organization_id
  AND w.slug = 'default';

UPDATE agents a
SET workspace_id = w.id
FROM workspaces w
WHERE a.workspace_id IS NULL
  AND a.organization_id = w.organization_id
  AND w.slug = 'default';

UPDATE workspaces w
SET kind = 'demo'
WHERE w.slug = 'default'
  AND EXISTS (
      SELECT 1 FROM knowledge_bases kb
      WHERE kb.organization_id = w.organization_id
        AND (kb.name ILIKE '%demo%' OR kb.name ILIKE '%farmacia%')
  );

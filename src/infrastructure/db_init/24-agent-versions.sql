-- =============================================================================
-- Agent versions — snapshot inmutable de configuración de agentes
-- Espejo SQL de la migración alembic 021_agent_versions (bases nuevas).
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'staging', 'production', 'archived')),
    config_snapshot JSONB NOT NULL DEFAULT '{}',
    notes TEXT,
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, version_number)
);

CREATE INDEX IF NOT EXISTS idx_agent_versions_agent
    ON agent_versions(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_versions_org
    ON agent_versions(organization_id);

-- Identidad del agente: slug único por organización + estado del ciclo de vida.
ALTER TABLE agents ADD COLUMN IF NOT EXISTS slug VARCHAR(255);
ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR(20)
    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_org_slug
    ON agents(organization_id, slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agents_org_status ON agents(organization_id, status);
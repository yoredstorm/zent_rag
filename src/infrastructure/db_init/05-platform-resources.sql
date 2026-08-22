-- =============================================================================
-- Platform Resources — Projects, Knowledge Bases, Agents, Connectors, Audit
-- =============================================================================
-- Jerarquía: organizations -> projects -> knowledge_bases/agents/connectors.
-- Todo recurso tiene organization_id OBLIGATORIO (raíz del aislamiento) y
-- project_id opcional. Nunca se consulta un recurso sin filtrar por organización.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Tabla: projects — Agrupación de recursos dentro de una organización
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_projects_organization ON projects(organization_id);

-- -----------------------------------------------------------------------------
-- Tabla: knowledge_bases — Bases de conocimiento (vectores en Qdrant)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    embedding_model VARCHAR(100),
    chunking_strategy VARCHAR(20) NOT NULL DEFAULT 'fixed',
    chunk_size INTEGER NOT NULL DEFAULT 1200,
    chunk_overlap INTEGER NOT NULL DEFAULT 150,
    retrieval_strategy VARCHAR(20) NOT NULL DEFAULT 'vector',
    reranker VARCHAR(50),
    metadata_schema JSONB NOT NULL DEFAULT '{}',
    config_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_kbs_organization ON knowledge_bases(organization_id);
CREATE INDEX IF NOT EXISTS idx_kbs_project ON knowledge_bases(project_id);

-- -----------------------------------------------------------------------------
-- Tabla: agents — Agentes conversacionales configurados por la organización
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    system_prompt TEXT,
    tools JSONB DEFAULT '[]',          -- Lista de tools habilitadas (sql_expert, rag, web...)
    model VARCHAR(100),                -- Modelo LLM del agente
    config_json JSONB DEFAULT '{}',
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_agents_organization ON agents(organization_id);
CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);

-- -----------------------------------------------------------------------------
-- Tabla: connectors — Fuentes de datos registradas (sql/api/files)
-- =============================================================================
-- Las credenciales NUNCA se guardan en config_json: van a HashiCorp Vault
-- (vía infrastructure.secrets.vault) bajo secret/<type>/<connector_id>.
-- config_json solo lleva parámetros no sensibles (host, schema allowlist...).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS connectors (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('sql', 'api', 'files')),
    config_json JSONB DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_connectors_organization ON connectors(organization_id);
CREATE INDEX IF NOT EXISTS idx_connectors_project ON connectors(project_id);

-- -----------------------------------------------------------------------------
-- Tabla: audit_logs — Registro de acciones sensibles (inmutables)
-- =============================================================================
-- Escrita por AuditLogService desde servicios mutadores. Una fila por acción.
-- Los clientes SOLO pueden leer sus propias filas (filtro por organization_id);
-- los admins de plataforma pueden consultar cross-organization.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = acción de plataforma
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,            -- ej: project.created, apikey.rotated, user.invited
    resource_type VARCHAR(100) NOT NULL,     -- ej: project, api_key, user, connector
    resource_id VARCHAR(255),
    ip_address VARCHAR(45),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_organization ON audit_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON audit_logs(resource_type, resource_id);

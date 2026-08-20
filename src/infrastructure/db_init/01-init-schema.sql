-- =============================================================================
-- Database Init Script — PostgreSQL para ZENT Multi-Tenant Platform
-- =============================================================================
-- Se ejecuta automáticamente al iniciar el contenedor PostgreSQL por primera vez.
-- Define el esquema relacional para Organizations, Users, Rate Limiting y Usage.
-- =============================================================================

-- Extensiones
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector para embeddings

-- -----------------------------------------------------------------------------
-- Tabla: organizations
-- Cada organization representa un cliente corporativo (tenant) con sus propias
-- configuraciones. Es la raíz del aislamiento multi-tenant: TODA tabla de datos
-- de cliente referencia organizations.id y toda query la filtra.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'deleted')),
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 600,
    max_tokens_per_request INTEGER NOT NULL DEFAULT 100000,
    llm_model_override VARCHAR(100),  -- Modelo LLM por defecto de la organización
    embedding_model_override VARCHAR(100),  -- Modelo de embedding por defecto
    config_json JSONB DEFAULT '{}',  -- Configuración adicional flexible
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Organization semilla para desarrollo
INSERT INTO organizations (id, name, status, rate_limit_per_minute)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Dev Organization',
    'active',
    999999  -- Sin límite práctico en desarrollo
) ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: users
-- Usuarios dentro de cada organization con referencias anonimizadas.
-- La membresía (rol por organización) vive en la tabla memberships (02-rbac.sql).
-- La columna role es legado informativo y se sincroniza con el rol de la membresía.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    external_id VARCHAR(255) NOT NULL,  -- ID del sistema cliente
    email_hash VARCHAR(64) NOT NULL,  -- SHA-256 del email (GDPR-friendly)
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ,
    UNIQUE (organization_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_users_organization_id ON users(organization_id);

-- Usuario semilla para desarrollo
INSERT INTO users (id, organization_id, external_id, email_hash, role)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    'dev-user',
    encode(sha256('dev@example.com'::bytea), 'hex'),
    'admin'
) ON CONFLICT (organization_id, external_id) DO NOTHING;

-- Usuario default (id = organization_id) para compatibilidad con Bearer token
INSERT INTO users (id, organization_id, external_id, email_hash, role)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'default-admin',
    encode(sha256('admin@dev.local'::bytea), 'hex'),
    'admin'
) ON CONFLICT (organization_id, external_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: rate_limit_counters
-- Contadores de rate limiting por minuto para cada organization.
-- Particionamiento implícito por minute_window.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    minute_window BIGINT NOT NULL,  -- Unix timestamp / 60
    counter INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (organization_id, minute_window)
);

-- -----------------------------------------------------------------------------
-- Tabla: usage_logs
-- Registro de uso de tokens para facturación por organization.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_logs (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    model VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_organization_id ON usage_logs(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at);

-- -----------------------------------------------------------------------------
-- Tabla: query_audit_log
-- Auditoría de consultas RAG para depuración y cumplimiento.
-- Cada fila registra el ciclo de vida completo de una query RAG.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS query_audit_log (
    query_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query_text TEXT NOT NULL,
    status VARCHAR(30) NOT NULL,
    retrieval_latency_ms DOUBLE PRECISION,
    llm_model VARCHAR(100),
    llm_latency_ms DOUBLE PRECISION,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    total_latency_ms DOUBLE PRECISION,
    error_message TEXT,
    trace_id VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_audit_organization ON query_audit_log(organization_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_audit_trace_id ON query_audit_log(trace_id);

-- -----------------------------------------------------------------------------
-- Tabla: documents (metadatos de documentos para RAG)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    external_id VARCHAR(255),  -- ID del documento en el sistema origen
    title VARCHAR(1024),
    source_url TEXT,
    content_hash VARCHAR(64),  -- SHA-256 del contenido (deduplicación)
    chunk_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'deleted')),
    metadata_json JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_organization ON documents(organization_id, status);

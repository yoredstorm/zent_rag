-- =============================================================================
-- Database Init Script — PostgreSQL para RAG-as-a-Service Platform
-- =============================================================================
-- Se ejecuta automáticamente al iniciar el contenedor PostgreSQL por primera vez.
-- Define el esquema relacional para Tenants, Usuarios, Rate Limiting y Facturación.
-- =============================================================================

-- Extensiones
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector para embeddings

-- -----------------------------------------------------------------------------
-- Tabla: tenants
-- Cada tenant representa un cliente corporativo con sus propias configuraciones.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    api_key_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 del API Key
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'suspended', 'deleted')),
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 600,
    max_tokens_per_request INTEGER NOT NULL DEFAULT 100000,
    llm_model_override VARCHAR(100),  -- Modelo LLM por defecto del tenant
    embedding_model_override VARCHAR(100),  -- Modelo de embedding por defecto
    config_json JSONB DEFAULT '{}',  -- Configuración adicional flexible
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tenant semilla para desarrollo
INSERT INTO tenants (id, name, api_key_hash, status, rate_limit_per_minute)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Dev Tenant',
    -- SHA-256 de "dev-api-key-change-in-production"
    encode(sha256('dev-api-key-change-in-production'::bytea), 'hex'),
    'active',
    999999  -- Sin límite práctico en desarrollo
) ON CONFLICT (id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: users
-- Usuarios dentro de cada tenant con referencias anonimizadas.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_id VARCHAR(255) NOT NULL,  -- ID del sistema cliente
    email_hash VARCHAR(64) NOT NULL,  -- SHA-256 del email (GDPR-friendly)
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at TIMESTAMPTZ,
    UNIQUE (tenant_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);

-- Usuario semilla para desarrollo
INSERT INTO users (id, tenant_id, external_id, email_hash, role)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    'dev-user',
    encode(sha256('dev@example.com'::bytea), 'hex'),
    'admin'
) ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- Usuario default (id = tenant_id) para compatibilidad con Bearer token
INSERT INTO users (id, tenant_id, external_id, email_hash, role)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    'default-admin',
    encode(sha256('admin@dev.local'::bytea), 'hex'),
    'admin'
) ON CONFLICT (tenant_id, external_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: rate_limit_counters
-- Contadores de rate limiting por minuto para cada tenant.
-- Particionamiento implícito por minute_window.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rate_limit_counters (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    minute_window BIGINT NOT NULL,  -- Unix timestamp / 60
    counter INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, minute_window)
);

-- -----------------------------------------------------------------------------
-- Tabla: usage_logs
-- Registro de uso de tokens para facturación por tenant.
-- Tabla particionable por mes para escalar en producción.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usage_logs (
    id BIGSERIAL PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
    model VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_logs_tenant_id ON usage_logs(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_logs_created_at ON usage_logs(created_at);

-- -----------------------------------------------------------------------------
-- Tabla: query_audit_log
-- Auditoría de consultas RAG para depuración y cumplimiento.
-- Cada fila registra el ciclo de vida completo de una query RAG.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS query_audit_log (
    query_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_query_audit_tenant ON query_audit_log(tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_audit_trace_id ON query_audit_log(trace_id);

-- -----------------------------------------------------------------------------
-- Tabla: documents (metadatos de documentos para RAG)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
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
    UNIQUE (tenant_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_tenant ON documents(tenant_id, status);

-- =============================================================================
-- Knowledge Platform — Sources, Ingestion Jobs (durable), Sync State
-- =============================================================================
-- ingestion_jobs es la fuente de verdad del estado de cada sync (retry,
-- resume y dead letter). Redis solo despierta al worker (wakeup).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Tabla: kb_sources — Fuentes de datos de una Knowledge Base
-- =============================================================================
-- config_json NUNCA lleva credenciales (Vault es el path productivo).
-- type: sql | file | csv | excel | web | s3 | api
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kb_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    knowledge_base_id UUID REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    -- Sin CHECK de tipo: el registro de conectores es extensible (nuevas
    -- fuentes = nueva clase + registro, sin migración). La API valida los
    -- 7 tipos soportados (pydantic).
    type VARCHAR(40) NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_kb_sources_organization ON kb_sources(organization_id);
CREATE INDEX IF NOT EXISTS idx_kb_sources_kb ON kb_sources(knowledge_base_id);

-- -----------------------------------------------------------------------------
-- Tabla: ingestion_jobs — Estado durable de cada job de ingestion
-- =============================================================================
-- status flow: pending -> running -> completed | failed -(retry_at)-> pending
--              failed -(attempts >= max_attempts)-> dead
--              canceled (por el usuario)
-- cursor_snapshot: checkpoint para resume (el connector la interpreta).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    knowledge_base_id UUID REFERENCES knowledge_bases(id) ON DELETE SET NULL,
    source_id UUID REFERENCES kb_sources(id) ON DELETE SET NULL,
    job_type VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'dead', 'canceled')),
    progress INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    records_processed BIGINT NOT NULL DEFAULT 0,
    records_failed BIGINT NOT NULL DEFAULT 0,
    error_summary JSONB NOT NULL DEFAULT '{}',
    cursor_snapshot JSONB,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    retry_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_org ON ingestion_jobs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_source ON ingestion_jobs(source_id);
CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_due ON ingestion_jobs(status, retry_at);

-- -----------------------------------------------------------------------------
-- Tabla: ingestion_job_errors — Historial de fallos por intento
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingestion_job_errors (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES ingestion_jobs(id) ON DELETE CASCADE,
    attempt INTEGER NOT NULL,
    error TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_errors_job ON ingestion_job_errors(job_id, attempt);

-- -----------------------------------------------------------------------------
-- Tabla: source_sync_state — Cursor incremental por fuente
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_sync_state (
    source_id UUID PRIMARY KEY REFERENCES kb_sources(id) ON DELETE CASCADE,
    cursor_json JSONB,
    last_success_at TIMESTAMPTZ,
    last_error TEXT,
    last_processed_count BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Tabla: source_documents — Registry para update/delete detection
-- =============================================================================
-- Cada record indexado se registra con su external_id y content_hash.
-- Un sync completo compara y marca 'deleted' los que ya no existen
-- (delete detection) o cambian de hash (update detection).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_documents (
    id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES kb_sources(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    document_id UUID NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deleted')),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS idx_source_documents_source ON source_documents(source_id, status);

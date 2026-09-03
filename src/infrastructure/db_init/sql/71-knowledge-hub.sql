-- =============================================================================
-- PROMPT 46 — AI Knowledge Hub v2 (Auto-Discovery & Curation) (065)
-- =============================================================================

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(150) NOT NULL,
    source_type VARCHAR(20) NOT NULL DEFAULT 'url',
    config JSONB NOT NULL DEFAULT '{}',
    refresh_interval_h INT NOT NULL DEFAULT 24,
    last_refresh_at TIMESTAMPTZ,
    next_refresh_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_sources_org
    ON knowledge_sources(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_refreshes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    docs_found INT NOT NULL DEFAULT 0,
    docs_added INT NOT NULL DEFAULT 0,
    docs_duplicated INT NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms INT
);
CREATE INDEX IF NOT EXISTS idx_knowledge_refreshes_source
    ON knowledge_refreshes(source_id, started_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    query VARCHAR(300) NOT NULL,
    intent VARCHAR(30),
    occurrences INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, query)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_org
    ON knowledge_gaps(organization_id, status, occurrences DESC);

-- Enriquecer documents (metadatos de curación + deduplicación):
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS category VARCHAR(60),
    ADD COLUMN IF NOT EXISTS author VARCHAR(120),
    ADD COLUMN IF NOT EXISTS freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS signature VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_documents_signature
    ON documents(organization_id, signature);
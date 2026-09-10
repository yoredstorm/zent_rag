-- =============================================================================
-- Data Onboarding — hechos extraídos de documentos (partes, fechas, montos, cláusulas)
-- =============================================================================

CREATE TABLE IF NOT EXISTS document_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    session_id UUID,
    source_id UUID,
    insight_type VARCHAR(40) NOT NULL,
    key VARCHAR(200) NOT NULL,
    value TEXT NOT NULL,
    normalized_value TEXT,
    evidence TEXT,
    page INTEGER,
    confidence VARCHAR(10) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by UUID,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_insights_org_source
    ON document_insights(organization_id, source_id, status);
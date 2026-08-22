-- =============================================================================
-- SQL Audit — registro de ejecuciones del motor Text-to-SQL
-- =============================================================================
-- Registra question, generated_sql, tablas, tiempo, filas, costo y estado.
-- NUNCA registra credenciales ni contenido de filas de negocio.
-- =============================================================================

CREATE TABLE IF NOT EXISTS sql_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id UUID,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    question TEXT NOT NULL,
    generated_sql TEXT,
    tables JSONB NOT NULL DEFAULT '[]',
    execution_time_ms DOUBLE PRECISION DEFAULT 0,
    rows INTEGER DEFAULT 0,
    cost DOUBLE PRECISION,
    status VARCHAR(30) NOT NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sql_audit_org
    ON sql_audit_logs(organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sql_audit_status
    ON sql_audit_logs(organization_id, status, created_at DESC);

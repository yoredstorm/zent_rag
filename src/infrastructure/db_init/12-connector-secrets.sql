-- =============================================================================
-- Connector Secrets — credenciales cifradas (AES-GCM) de conectores
-- =============================================================================
-- Fallback local al SecretStore de Vault. NUNCA texto plano: el payload
-- es nonce(12B) + ciphertext AES-256-GCM con CONNECTOR_SECRETS_KEY.
-- =============================================================================

CREATE TABLE IF NOT EXISTS connector_secrets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    connector_id UUID NOT NULL,
    ciphertext BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, connector_id)
);

CREATE INDEX IF NOT EXISTS idx_connector_secrets_org
    ON connector_secrets(organization_id);

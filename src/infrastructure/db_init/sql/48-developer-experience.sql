-- =============================================================================
-- PROMPT 23 — Developer Experience (espejo de la migración 042_developer_experience.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    url VARCHAR(500) NOT NULL,
    secret_enc VARCHAR(600) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    delivery_count INT NOT NULL DEFAULT 0,
    fail_count INT NOT NULL DEFAULT 0,
    last_delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, event_type, url)
);
CREATE INDEX IF NOT EXISTS idx_webhook_subs_org ON webhook_subscriptions(organization_id, enabled);

CREATE TABLE IF NOT EXISTS platform_changelog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version VARCHAR(30) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT NOT NULL,
    is_public BOOLEAN NOT NULL DEFAULT true,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO platform_changelog (version, title, body) VALUES
('v2.4.0', 'Public API & Developer Center', 'Endpoint público por deployment con structured output, logs de API y hardening de keys.'),
('v2.5.0', 'Enterprise', 'SSO OIDC, SCIM 2.0, rotación de API keys y política de expiración.'),
('v2.6.0', 'Model Gateway', 'Routing de modelos por condición con A/B, presupuestos por modelo y fallback automático.')
ON CONFLICT DO NOTHING;
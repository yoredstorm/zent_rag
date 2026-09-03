-- =============================================================================
-- PROMPT 24 — Partner Ecosystem (espejo de la migración 043_partners.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS partners (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    name VARCHAR(200) NOT NULL,
    contact_email VARCHAR(320),
    rev_share_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    white_label_enabled BOOLEAN NOT NULL DEFAULT false,
    branding JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS partner_id UUID;

CREATE TABLE IF NOT EXISTS partner_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type VARCHAR(40) NOT NULL DEFAULT 'api_query',
    tokens INT NOT NULL DEFAULT 0,
    cost DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_partner_usage_partner ON partner_usage(partner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS partner_commissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID NOT NULL,
    period VARCHAR(7) NOT NULL,
    revenue_cents INT NOT NULL DEFAULT 0,
    commission_cents INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'payable',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partner_id, period)
);

CREATE TABLE IF NOT EXISTS partner_subtenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    partner_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    commission_share_pct DOUBLE PRECISION NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (partner_id, organization_id)
);

CREATE TABLE IF NOT EXISTS integrations_catalog (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(60) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    category VARCHAR(60) NOT NULL DEFAULT 'general',
    description TEXT,
    oauth_url_template VARCHAR(500),
    docs_url VARCHAR(300),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO integrations_catalog (key, name, category, description, oauth_url_template) VALUES
('google_drive', 'Google Drive', 'storage', 'Conecta fuentes de Google Drive.', 'https://accounts.google.com/o/oauth2/v2/auth?client_id={client_id}&redirect_uri={redirect_uri}&scope=drive.readonly'),
('slack', 'Slack', 'collaboration', 'Publica respuestas de agentes en canales.', 'https://slack.com/oauth/v2/authorize?client_id={client_id}&scope=chat:write'),
('salesforce', 'Salesforce', 'crm', 'Consulta y actualiza oportunidades.', 'https://login.salesforce.com/services/oauth2/authorize?client_id={client_id}&redirect_uri={redirect_uri}'),
('hubspot', 'HubSpot', 'crm', 'Contactos y deals desde agentes.', 'https://app.hubspot.com/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}&scope=crm.objects.contacts.read'),
('shopify', 'Shopify', 'commerce', 'Stock y pedidos de la tienda.', 'https://{shop}.myshopify.com/admin/oauth/authorize?client_id={client_id}&scope=read_products'),
('notion', 'Notion', 'knowledge', 'Sincroniza páginas de Notion como fuentes.', 'https://api.notion.com/v1/oauth/authorize?client_id={client_id}&redirect_uri={redirect_uri}')
ON CONFLICT (key) DO NOTHING;
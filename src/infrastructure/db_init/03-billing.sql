-- =============================================================================
-- Billing Schema — Planes, Suscripciones, API Tokens y Cuotas
-- =============================================================================
-- Gestiona el modelo de negocio multi-plan con trial gratuito,
-- suscripciones mensuales/anuales, tokens de API y contadores de uso.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Tabla: plans — Definición de planes disponibles
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    price_monthly_cents INTEGER NOT NULL DEFAULT 0,      -- Precio mensual en centavos
    price_annual_cents INTEGER NOT NULL DEFAULT 0,       -- Precio anual en centavos
    requests_per_month INTEGER NOT NULL DEFAULT 500,     -- Cuota de requests mensuales
    max_tenants INTEGER NOT NULL DEFAULT 1,              -- Máx tenants permitidos
    max_users_per_tenant INTEGER NOT NULL DEFAULT 10,    -- Máx usuarios por tenant
    features JSONB NOT NULL DEFAULT '[]',                -- Lista de features (strings)
    is_public BOOLEAN NOT NULL DEFAULT true,             -- Visible en página de pricing
    is_trial BOOLEAN NOT NULL DEFAULT false,             -- Es el plan de trial gratuito
    trial_days INTEGER NOT NULL DEFAULT 0,               -- Días de trial (0 = sin trial)
    sort_order INTEGER NOT NULL DEFAULT 0,               -- Orden en UI
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- Planes predefinidos
-- -----------------------------------------------------------------------------
INSERT INTO plans (id, name, display_name, description, price_monthly_cents, price_annual_cents, requests_per_month, max_tenants, max_users_per_tenant, features, is_public, is_trial, trial_days, sort_order) VALUES
(
    '10000000-0000-0000-0000-000000000001',
    'trial',
    'Free Trial',
    'Prueba gratuita de 30 días con 500 consultas. Sin tarjeta de crédito.',
    0, 0,
    500, 1, 5,
    '["RAG básico", "1 tenant", "5 usuarios", "Historial 7 días", "Embeddings locales", "Soporte por email"]'::jsonb,
    true, true, 30, 1
),
(
    '10000000-0000-0000-0000-000000000002',
    'starter',
    'Starter',
    'Para equipos pequeños que necesitan RAG en producción.',
    4900, 47000,
    5000, 3, 20,
    '["RAG avanzado", "3 tenants", "20 usuarios", "SQL Expert", "Historial 30 días", "Soporte prioritario", "Dashboard analytics"]'::jsonb,
    true, false, 0, 2
),
(
    '10000000-0000-0000-0000-000000000003',
    'pro',
    'Professional',
    'Para empresas con alto volumen de consultas y necesidades avanzadas.',
    14900, 143000,
    25000, 10, 100,
    '["RAG avanzado", "10 tenants", "100 usuarios", "SQL Expert", "Historial 90 días", "Soporte 24/7", "Dashboard analytics", "Webhooks", "API dedicada", "SSO"]'::jsonb,
    true, false, 0, 3
),
(
    '10000000-0000-0000-0000-000000000004',
    'enterprise',
    'Enterprise',
    'Solución on-premise o cloud dedicada. Sin límites de requests. Contrato anual.',
    49900, 479000,
    100000, 999, 9999,
    '["Todo lo de Pro", "Tenants ilimitados", "Usuarios ilimitados", "Modelo LLM custom", "On-premise", "SLA 99.9%", "Gerente de cuenta", "Facturación por uso excedente"]'::jsonb,
    true, false, 0, 4
) ON CONFLICT (name) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Tabla: billing_cycles — Períodos de facturación
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS billing_cycles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    billing_period_start TIMESTAMPTZ NOT NULL,             -- Inicio del ciclo
    billing_period_end TIMESTAMPTZ NOT NULL,               -- Fin del ciclo
    is_current BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_billing_cycle_period UNIQUE (billing_period_start, billing_period_end)
);

-- -----------------------------------------------------------------------------
-- Tabla: subscriptions — Suscripción de un tenant a un plan
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES plans(id),
    billing_cycle_id UUID REFERENCES billing_cycles(id),
    status VARCHAR(30) NOT NULL DEFAULT 'trialing'
        CHECK (status IN ('trialing', 'active', 'past_due', 'canceled', 'expired', 'paused')),
    billing_interval VARCHAR(10) NOT NULL DEFAULT 'monthly'
        CHECK (billing_interval IN ('monthly', 'annual')),
    trial_start TIMESTAMPTZ,
    trial_end TIMESTAMPTZ,
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    auto_renew BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_tenant ON subscriptions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_active_tenant
    ON subscriptions(tenant_id) WHERE status IN ('trialing', 'active');

-- -----------------------------------------------------------------------------
-- Tabla: api_tokens — Tokens de API por suscripción
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,                 -- SHA-256 del token
    token_prefix VARCHAR(16) NOT NULL,                      -- "rag_live_" o "rag_test_"
    name VARCHAR(255) NOT NULL DEFAULT 'Default',           -- Etiqueta descriptiva
    scopes JSONB NOT NULL DEFAULT '["rag:query", "rag:ingest"]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,                                 -- Opcional: expiración del token
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_subscription ON api_tokens(subscription_id);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_tokens_active_subscription
    ON api_tokens(subscription_id) WHERE is_active = true;

-- -----------------------------------------------------------------------------
-- Tabla: request_quota — Contador de requests por suscripción por mes
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS request_quota (
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    quota_year INTEGER NOT NULL,                            -- Año (ej: 2026)
    quota_month INTEGER NOT NULL CHECK (quota_month BETWEEN 1 AND 12),
    request_count BIGINT NOT NULL DEFAULT 0,
    token_count BIGINT NOT NULL DEFAULT 0,                  -- Tokens totales consumidos
    reset_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (subscription_id, quota_year, quota_month)
);

-- -----------------------------------------------------------------------------
-- Auto-crear subscription trial para tenant de desarrollo
-- -----------------------------------------------------------------------------
INSERT INTO subscriptions (id, tenant_id, plan_id, status, billing_interval,
    trial_start, trial_end, current_period_start, current_period_end)
SELECT
    '20000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'trialing',
    'monthly',
    NOW(),
    NOW() + INTERVAL '30 days',
    NOW(),
    NOW() + INTERVAL '30 days'
WHERE EXISTS (SELECT 1 FROM tenants WHERE id = '00000000-0000-0000-0000-000000000001')
AND NOT EXISTS (SELECT 1 FROM subscriptions WHERE tenant_id = '00000000-0000-0000-0000-000000000001');

-- API Token de desarrollo (SHA-256 del token en texto plano)
-- Token: rag_test_dev_token_for_local_testing_123
INSERT INTO api_tokens (id, subscription_id, token_hash, token_prefix, name, scopes)
SELECT
    '30000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    encode(sha256('rag_test_dev_token_for_local_testing_123'::bytea), 'hex'),
    'rag_test_',
    'Dev Token',
    '["rag:query", "rag:ingest", "admin:*"]'::jsonb
WHERE EXISTS (SELECT 1 FROM subscriptions WHERE id = '20000000-0000-0000-0000-000000000001')
AND NOT EXISTS (SELECT 1 FROM api_tokens WHERE subscription_id = '20000000-0000-0000-0000-000000000001');

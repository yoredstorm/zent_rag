-- =============================================================================
-- Billing Schema — Planes, Suscripciones, API Keys y Cuotas
-- =============================================================================
-- Gestiona el modelo de negocio multi-plan con trial gratuito,
-- suscripciones mensuales/anuales, API keys por organización y cuotas.
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
    max_organizations INTEGER NOT NULL DEFAULT 1,        -- Máx organizaciones permitidas
    max_users_per_organization INTEGER NOT NULL DEFAULT 10, -- Máx usuarios por organización
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
INSERT INTO plans (id, name, display_name, description, price_monthly_cents, price_annual_cents, requests_per_month, max_organizations, max_users_per_organization, features, is_public, is_trial, trial_days, sort_order) VALUES
(
    '10000000-0000-0000-0000-000000000001',
    'trial',
    'Free Trial',
    'Prueba gratuita de 30 días con 500 consultas. Sin tarjeta de crédito.',
    0, 0,
    500, 1, 5,
    '["RAG básico", "1 organización", "5 usuarios", "Historial 7 días", "Embeddings locales", "Soporte por email"]'::jsonb,
    true, true, 30, 1
),
(
    '10000000-0000-0000-0000-000000000002',
    'starter',
    'Starter',
    'Para equipos pequeños que necesitan RAG en producción.',
    4900, 47000,
    5000, 3, 20,
    '["RAG avanzado", "3 organizaciones", "20 usuarios", "SQL Expert", "Historial 30 días", "Soporte prioritario", "Dashboard analytics"]'::jsonb,
    true, false, 0, 2
),
(
    '10000000-0000-0000-0000-000000000003',
    'pro',
    'Professional',
    'Para empresas con alto volumen de consultas y necesidades avanzadas.',
    14900, 143000,
    25000, 10, 100,
    '["RAG avanzado", "10 organizaciones", "100 usuarios", "SQL Expert", "Historial 90 días", "Soporte 24/7", "Dashboard analytics", "Webhooks", "API dedicada", "SSO"]'::jsonb,
    true, false, 0, 3
),
(
    '10000000-0000-0000-0000-000000000004',
    'enterprise',
    'Enterprise',
    'Solución on-premise o cloud dedicada. Sin límites de requests. Contrato anual.',
    49900, 479000,
    100000, 999, 9999,
    '["Todo lo de Pro", "Organizaciones ilimitadas", "Usuarios ilimitados", "Modelo LLM custom", "On-premise", "SLA 99.9%", "Gerente de cuenta", "Facturación por uso excedente"]'::jsonb,
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
-- Tabla: subscriptions — Suscripción de una organización a un plan
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_subscriptions_organization ON subscriptions(organization_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_active_organization
    ON subscriptions(organization_id) WHERE status IN ('trialing', 'active');

-- -----------------------------------------------------------------------------
-- Tabla: api_keys — API keys de una organización (múltiples, con scopes)
-- =============================================================================
-- La identidad de una key se deriva EXCLUSIVAMENTE de su hash SHA-256.
-- Nunca se confía en headers (X-Organization-Id / X-User-Id) ni en bodies.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Default',           -- Etiqueta descriptiva
    key_hash VARCHAR(64) NOT NULL UNIQUE,                   -- SHA-256 del token (nunca plaintext)
    key_prefix VARCHAR(16) NOT NULL,                        -- "rag_live_" o "rag_test_"
    scopes JSONB NOT NULL DEFAULT '["rag:read", "rag:write"]'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,                                 -- Opcional: expiración del token
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_organization ON api_keys(organization_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_active_name
    ON api_keys(organization_id, name) WHERE is_active = true;

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
-- Auto-crear subscription trial para la organización de desarrollo
-- -----------------------------------------------------------------------------
INSERT INTO subscriptions (id, organization_id, plan_id, status, billing_interval,
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
WHERE EXISTS (SELECT 1 FROM organizations WHERE id = '00000000-0000-0000-0000-000000000001')
AND NOT EXISTS (SELECT 1 FROM subscriptions WHERE organization_id = '00000000-0000-0000-0000-000000000001');

-- El API key de desarrollo (scope admin:*) se siembra SOLO si
-- RAG_SEED_DEMO_DATA=true, vía 07-dev-seed.sh (nunca en producción).

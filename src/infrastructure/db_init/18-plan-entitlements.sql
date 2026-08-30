-- =============================================================================
-- Plan entitlements — configurable limits/features + subscription_events
-- =============================================================================
-- plans.max_* and plans.features remain. Enforcement reads plan_entitlements.
-- =============================================================================

CREATE TABLE IF NOT EXISTS plan_entitlements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    key VARCHAR(80) NOT NULL,
    value_type VARCHAR(20) NOT NULL CHECK (value_type IN ('bool', 'int', 'bigint')),
    value_bool BOOLEAN,
    value_int BIGINT,
    UNIQUE (plan_id, key)
);

CREATE INDEX IF NOT EXISTS idx_plan_entitlements_plan ON plan_entitlements(plan_id);

CREATE TABLE IF NOT EXISTS subscription_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    event_type VARCHAR(40) NOT NULL CHECK (
        event_type IN (
            'created', 'plan_changed', 'paused', 'suspended',
            'canceled', 'usage_reset'
        )
    ),
    from_plan_id UUID,
    to_plan_id UUID,
    actor_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscription_events_org
    ON subscription_events(organization_id, created_at DESC);

INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
SELECT id, 'monthly_requests', 'int', requests_per_month FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
SELECT id, 'max_users', 'int', max_users_per_organization FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
SELECT id, 'max_agents', 'int', max_agents FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
SELECT id, 'max_knowledge_bases', 'int', max_knowledge_bases FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
SELECT id, 'max_connectors', 'int', max_connectors FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
SELECT id, 'api_access', 'bool', true FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
SELECT id, 'custom_models', 'bool', (name = 'enterprise') FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
SELECT id, 'embed_widget', 'bool', (name IN ('pro', 'enterprise')) FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
SELECT id, 'eval_ui', 'bool', (name IN ('pro', 'enterprise')) FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
SELECT id, 'sso', 'bool', false FROM plans
ON CONFLICT (plan_id, key) DO NOTHING;

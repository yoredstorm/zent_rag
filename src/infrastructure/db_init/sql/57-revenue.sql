-- =============================================================================
-- PROMPT 32 — Revenue Intelligence & ARR (espejo de 051_revenue.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS subscription_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID,
    organization_id UUID NOT NULL,
    event_type VARCHAR(30) NOT NULL,
    from_plan_id UUID,
    to_plan_id UUID,
    actor_user_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sub_events_org_time ON subscription_events(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sub_events_type_time ON subscription_events(event_type, created_at);

ALTER TABLE subscription_events ADD COLUMN IF NOT EXISTS plan_name VARCHAR(50);
ALTER TABLE subscription_events ADD COLUMN IF NOT EXISTS mrr_cents INT NOT NULL DEFAULT 0;

-- Extender CHECK de event_type (creado en PROMPT 12 con lista previa).
ALTER TABLE subscription_events DROP CONSTRAINT IF EXISTS subscription_events_event_type_check;
ALTER TABLE subscription_events ADD CONSTRAINT subscription_events_event_type_check
CHECK (event_type IN ('created', 'plan_changed', 'usage_reset', 'canceled',
'expired', 'renewed', 'upgraded', 'downgraded'));

INSERT INTO subscription_events (subscription_id, organization_id, event_type,
    plan_name, mrr_cents, created_at)
SELECT s.id, s.organization_id, 'created', p.name,
    CASE WHEN p.is_trial THEN 0 ELSE p.price_monthly_cents END,
    s.created_at
FROM subscriptions s JOIN plans p ON p.id = s.plan_id
WHERE s.status IN ('trialing', 'active')
AND NOT EXISTS (
    SELECT 1 FROM subscription_events e
    WHERE e.subscription_id = s.id AND e.event_type = 'created'
)
ON CONFLICT DO NOTHING;
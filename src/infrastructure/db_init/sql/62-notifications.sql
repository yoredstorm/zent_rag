-- =============================================================================
-- PROMPT 37 — Multi-Tenant Notifications & Webhooks v2 (espejo de 056)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenant_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    channel VARCHAR(20) NOT NULL DEFAULT 'in_app',
    event_type VARCHAR(60) NOT NULL,
    title VARCHAR(200) NOT NULL,
    body TEXT,
    data JSONB NOT NULL DEFAULT '{}',
    read_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenant_notifications_org ON tenant_notifications(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_notifications_unread ON tenant_notifications(organization_id, read_at) WHERE read_at IS NULL;

CREATE TABLE IF NOT EXISTS notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL UNIQUE,
    channels JSONB NOT NULL DEFAULT '{"in_app": true, "email": true, "webhook": true}',
    events JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type VARCHAR(60) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    signature VARCHAR(128),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ,
    last_status_code INT,
    latency_ms DOUBLE PRECISION,
    error TEXT,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_pending ON webhook_deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_org_time ON webhook_deliveries(organization_id, created_at DESC);
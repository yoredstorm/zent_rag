-- =============================================================================
-- PROMPT 45 — AI Chat Analytics & Conversational Insights v2 (064)
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversation_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    topic VARCHAR(50) NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]',
    message_count INT NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, topic)
);
CREATE INDEX IF NOT EXISTS idx_conversation_topics_org
    ON conversation_topics(organization_id, message_count DESC);

CREATE TABLE IF NOT EXISTS conversation_insights (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    date DATE NOT NULL,
    metric_key VARCHAR(40) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, date, metric_key)
);

CREATE TABLE IF NOT EXISTS chat_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    session_id UUID,
    event_type VARCHAR(30) NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chat_events_org
    ON chat_events(organization_id, created_at);
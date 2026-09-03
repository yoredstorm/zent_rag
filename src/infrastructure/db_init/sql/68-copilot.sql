-- =============================================================================
-- PROMPT 43 — AI Copilot & Assistant Platform v2 (espejo de 062_copilot.py)
-- =============================================================================

CREATE TABLE IF NOT EXISTS marketplace_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    slug VARCHAR(80) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(40) NOT NULL DEFAULT 'general',
    tags JSONB NOT NULL DEFAULT '[]',
    prompt_template TEXT,
    config_template JSONB NOT NULL DEFAULT '{}',
    rating DOUBLE PRECISION NOT NULL DEFAULT 0,
    installs INT NOT NULL DEFAULT 0,
    featured BOOLEAN NOT NULL DEFAULT false,
    status VARCHAR(20) NOT NULL DEFAULT 'published',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS marketplace_installs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    marketplace_agent_id UUID NOT NULL,
    agent_id UUID,
    status VARCHAR(20) NOT NULL DEFAULT 'installed',
    installed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at TIMESTAMPTZ,
    usage_count INT NOT NULL DEFAULT 0,
    UNIQUE (organization_id, marketplace_agent_id, status)
);

CREATE TABLE IF NOT EXISTS copilot_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id UUID,
    title VARCHAR(200) NOT NULL DEFAULT 'Nueva conversación',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_copilot_sessions_org
    ON copilot_sessions(organization_id, last_activity_at DESC);

CREATE TABLE IF NOT EXISTS copilot_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    role VARCHAR(15) NOT NULL DEFAULT 'user',
    content TEXT NOT NULL,
    intent VARCHAR(30),
    resolved_agent_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_copilot_messages_session
    ON copilot_messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS assistant_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    assistant_key VARCHAR(80) NOT NULL,
    events INT NOT NULL DEFAULT 0,
    last_event_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, assistant_key)
);

-- Seed del marketplace (5 agentes) — ver 062_copilot.py para el texto completo.
-- Control Center inbox (notify only; does not gate org access)
CREATE TABLE IF NOT EXISTS platform_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(80) NOT NULL,
    organization_id UUID,
    title VARCHAR(240) NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_platform_notifications_unread
    ON platform_notifications (created_at DESC)
    WHERE read_at IS NULL;

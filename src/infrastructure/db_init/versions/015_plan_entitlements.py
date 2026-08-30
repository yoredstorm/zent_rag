"""Plan entitlements + subscription_events.

Revision ID: 015
Revises: 014
Create Date: 2026-08-29
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS plan_entitlements (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
            key VARCHAR(80) NOT NULL,
            value_type VARCHAR(20) NOT NULL
                CHECK (value_type IN ('bool', 'int', 'bigint')),
            value_bool BOOLEAN,
            value_int BIGINT,
            UNIQUE (plan_id, key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_plan_entitlements_plan "
        "ON plan_entitlements(plan_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            subscription_id UUID NOT NULL REFERENCES subscriptions(id)
                ON DELETE CASCADE,
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
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_subscription_events_org "
        "ON subscription_events(organization_id, created_at DESC)"
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
        SELECT id, 'monthly_requests', 'int', requests_per_month FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
        SELECT id, 'max_users', 'int', max_users_per_organization FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
        SELECT id, 'max_agents', 'int', max_agents FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
        SELECT id, 'max_knowledge_bases', 'int', max_knowledge_bases FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_int)
        SELECT id, 'max_connectors', 'int', max_connectors FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
        SELECT id, 'api_access', 'bool', true FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
        SELECT id, 'custom_models', 'bool', (name = 'enterprise') FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
        SELECT id, 'embed_widget', 'bool', (name IN ('pro', 'enterprise')) FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
        SELECT id, 'eval_ui', 'bool', (name IN ('pro', 'enterprise')) FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO plan_entitlements (plan_id, key, value_type, value_bool)
        SELECT id, 'sso', 'bool', false FROM plans
        ON CONFLICT (plan_id, key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscription_events")
    op.execute("DROP TABLE IF EXISTS plan_entitlements")

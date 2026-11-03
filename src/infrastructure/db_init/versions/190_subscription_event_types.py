"""Tipos de evento de suscripción: suspender y pausar.

Revision ID: 185
Revises: 184

`POST /platform/organizations/{id}/suspend` y `/pause` registran un evento en
`subscription_events`, pero la constraint original solo admitía created,
plan_changed, usage_reset, canceled, expired, renewed, upgraded y downgraded.
Resultado: la transición se aplicaba y la petición terminaba en 500.
"""
from __future__ import annotations

from alembic import op

revision: str = "190"
down_revision: str = "189"
branch_labels = None
depends_on = None

_EVENT_TYPES = (
    "'created', 'plan_changed', 'usage_reset', 'canceled', 'expired', "
    "'renewed', 'upgraded', 'downgraded', 'suspended', 'paused', 'resumed'"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE subscription_events "
        "DROP CONSTRAINT IF EXISTS subscription_events_event_type_check"
    )
    op.execute(
        "ALTER TABLE subscription_events ADD CONSTRAINT "
        "subscription_events_event_type_check "
        f"CHECK (event_type IN ({_EVENT_TYPES}))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE subscription_events "
        "DROP CONSTRAINT IF EXISTS subscription_events_event_type_check"
    )
    op.execute(
        "ALTER TABLE subscription_events ADD CONSTRAINT "
        "subscription_events_event_type_check "
        "CHECK (event_type IN ('created', 'plan_changed', 'usage_reset', "
        "'canceled', 'expired', 'renewed', 'upgraded', 'downgraded'))"
    )

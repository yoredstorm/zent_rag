"""Workflow studio v2 — scheduler, editor_state, inbound hook, low-stock template.

Revision ID: 087
Revises: 086
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision: str = "087"
down_revision: str = "086"
branch_labels = None
depends_on = None

_LOW_STOCK_STEPS = [
    {
        "type": "api_call",
        "config": {
            "url": "https://stock.example.com/qty",
            "method": "GET",
            "json_path": "quantity",
        },
    },
    {
        "type": "kb_query",
        "config": {
            "query": "politica de reposicion {{steps.0.output.extracted}}",
            "limit": 5,
        },
    },
    {
        "type": "condition",
        "config": {"field": "steps.0.output.extracted", "operator": "<", "value": "10"},
        "then": [
            {
                "type": "notify",
                "config": {
                    "channel": "email",
                    "title": "Stock bajo",
                    "message": "Quedan {{steps.0.output.extracted}} unidades",
                },
            },
            {
                "type": "notify",
                "config": {
                    "channel": "webhook",
                    "title": "Stock bajo",
                    "message": "qty={{steps.0.output.extracted}}",
                    "data": {"stock": "{{steps.0.output.extracted}}"},
                },
            },
        ],
        "else": [
            {
                "type": "notify",
                "config": {
                    "channel": "in_app",
                    "title": "Stock OK",
                    "message": "qty={{steps.0.output.extracted}}",
                },
            }
        ],
    },
]


def upgrade() -> None:
    op.execute("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS editor_state JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS trigger_config "
        "JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    bind = op.get_bind()
    bind.execute(
        text(
            "INSERT INTO workflow_templates "
            "(slug, name, description, category, trigger_type, trigger_config, steps) "
            "VALUES "
            "(:slug, :name, :desc, :cat, :ttype, CAST(:tcfg AS jsonb), CAST(:steps AS jsonb)) "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {
            "slug": "low-stock-alert",
            "name": "Alerta de stock bajo",
            "desc": "Consulta stock cada 5 minutos, cruza con la KB y avisa por email y webhook.",
            "cat": "operations",
            "ttype": "schedule",
            "tcfg": json.dumps({"every_minutes": 5}),
            "steps": json.dumps(_LOW_STOCK_STEPS),
        },
    )


def downgrade() -> None:
    op.execute("DELETE FROM workflow_templates WHERE slug = 'low-stock-alert'")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS last_run_at")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS editor_state")
    op.execute("ALTER TABLE workflow_templates DROP COLUMN IF EXISTS trigger_config")

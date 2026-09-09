"""Phase 32C — Business Results, Intelligence packs y templates proactivos.

Revision ID: 090
Revises: 089
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision: str = "090"
down_revision: str = "089"
branch_labels = None
depends_on = None

_INTEL_PERMISSIONS = [
    ("40000000-0000-0000-0000-000000000090", "intelligence:read", "Ver resultados de inteligencia e inbox"),
    ("40000000-0000-0000-0000-000000000091", "intelligence:write", "Registrar resultados de inteligencia"),
]

_READER_ROLES = ("owner", "admin", "member", "viewer", "ai_engineer", "data_engineer", "developer", "analyst")
_MANAGER_ROLES = ("owner", "admin", "member")

_PACK_TEMPLATES = [
    {
        "slug": "daily-executive-sales-brief",
        "name": "Brief ejecutivo de ventas diario",
        "description": "Ventas de hoy vs ayer, análisis del agente y reporte por correo/in-app a las 18:00.",
        "category": "analytics",
        "trigger_type": "schedule",
        "trigger_config": {"daily": {"time": "18:00", "timezone": "America/Lima"}},
        "steps": [
            {
                "type": "query_business_data",
                "config": {"ask": "Ventas del día (ingresos, tickets, ticket promedio y producto top)"},
            },
            {
                "type": "query_business_data",
                "config": {"ask": "Ventas del día anterior para comparar" },
            },
            {
                "type": "set_variable",
                "config": {"name": "ventas_hoy", "value": "{{nodes.n1.output.answer}}"},
            },
            {
                "type": "set_variable",
                "config": {"name": "ventas_ayer", "value": "{{nodes.n2.output.answer}}"},
            },
            {
                "type": "llm",
                "config": {"prompt": "Analiza las ventas del día {{nodes.n1.output.answer}} frente a ayer {{nodes.n2.output.answer}}. Resume variación, anomalías y oportunidades en 3 bullets."},
            },
            {
                "type": "notify",
                "config": {"channel": "in_app", "title": "Brief diario de ventas", "message": "{{nodes.n5.output.text}}"},
            },
        ],
    },
    {
        "slug": "new-business-customer-verification",
        "name": "Verificación de contribuyente (cliente nuevo)",
        "description": "Con RUC verifica el contribuyente en SUNAT (sandbox demo-echo) y avisa si está inactivo.",
        "category": "operations",
        "trigger_type": "event",
        "trigger_config": {"event_type": "customer.created", "filters": {}},
        "steps": [
            {
                "type": "condition",
                "config": {"field": "trigger.ruc", "operator": "!=", "value": ""},
                "then": [
                    {
                        "type": "marketplace_action",
                        "config": {
                            "install_id": "{{_pack.demo_echo_install}}",
                            "action_id": "demo.echo",
                            "inputs": {"text": "{{trigger.ruc}}"},
                        },
                    },
                    {
                        "type": "llm",
                        "config": {"prompt": "El RUC {{trigger.ruc}} devolvió: {{steps.1.output.echo}}. Explica si el contribuyente parece activo o si hay que investigar."},
                    },
                ],
                "else": [
                    {"type": "notify", "config": {"channel": "in_app", "title": "Cliente sin RUC", "message": "El cliente {{trigger.name}} no tiene RUC; continúa sin verificación."}}
                ],
            }
        ],
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            title VARCHAR(180) NOT NULL,
            summary TEXT,
            section VARCHAR(40) NOT NULL DEFAULT 'reports',
            importance VARCHAR(12) NOT NULL DEFAULT 'INFO',
            metrics JSONB NOT NULL DEFAULT '{}',
            insights JSONB NOT NULL DEFAULT '[]',
            entities JSONB NOT NULL DEFAULT '[]',
            recommendations JSONB NOT NULL DEFAULT '[]',
            evidence JSONB NOT NULL DEFAULT '[]',
            actions_taken JSONB NOT NULL DEFAULT '[]',
            actions_available JSONB NOT NULL DEFAULT '[]',
            workflow_id UUID,
            workflow_run_id UUID,
            agent_run_id UUID,
            correlation_id VARCHAR(128),
            fingerprint VARCHAR(64),
            source VARCHAR(80) NOT NULL DEFAULT 'workflow',
            generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            freshness_seconds INT NOT NULL DEFAULT 0
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_results_org_time "
        "ON business_results(organization_id, section, generated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_business_results_entity "
        "ON business_results(organization_id, entities)"
    )

    for pid, code, desc in _INTEL_PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (id, code, description) VALUES (:pid, :code, :desc) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"pid": pid, "code": code, "desc": desc},
        )

    def _grant(permission: str, roles: tuple[str, ...]) -> None:
        role_list = ", ".join(f"'{r}'" for r in roles)
        bind.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                f"WHERE r.organization_id IS NULL AND r.name IN ({role_list}) "
                "AND p.code = :perm ON CONFLICT DO NOTHING"
            ),
            {"perm": permission},
        )

    _grant("intelligence:read", _READER_ROLES)
    _grant("intelligence:write", _MANAGER_ROLES)

    # Plantillas de negocio (proactive packs) — pasos nuevos del runtime 32A/32B.
    for tpl in _PACK_TEMPLATES:
        bind.execute(
            text(
                "INSERT INTO workflow_templates "
                "(slug, name, description, category, trigger_type, trigger_config, steps) "
                "VALUES (:slug, :name, :desc, :cat, :ttype, CAST(:tcfg AS jsonb), CAST(:steps AS jsonb)) "
                "ON CONFLICT (slug) DO NOTHING"
            ),
            {
                "slug": tpl["slug"],
                "name": tpl["name"],
                "desc": tpl["description"],
                "cat": tpl["category"],
                "ttype": tpl["trigger_type"],
                "tcfg": json.dumps(tpl["trigger_config"] or {}),
                "steps": json.dumps(tpl["steps"]),
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS business_results")
    for pid, _code, _desc in _INTEL_PERMISSIONS:
        op.execute(text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})
    for tpl in _PACK_TEMPLATES:
        op.execute(text("DELETE FROM workflow_templates WHERE slug = :slug"), {"slug": tpl["slug"]})

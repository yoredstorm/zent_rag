"""Phase 32B — Integration Marketplace & External Capability Runtime.

Revision ID: 089
Revises: 088
"""
from __future__ import annotations

import json

from alembic import op
from sqlalchemy import text

revision: str = "089"
down_revision: str = "088"
branch_labels = None
depends_on = None

_MARKET_PERMISSIONS = [
    ("40000000-0000-0000-0000-000000000080", "marketplace:read", "Ver marketplace, instalaciones y evidencia"),
    ("40000000-0000-0000-0000-000000000081", "marketplace:install", "Instalar integraciones del marketplace"),
    ("40000000-0000-0000-0000-000000000082", "marketplace:manage", "Gestionar instalaciones (acciones, límites, propósito)"),
    ("40000000-0000-0000-0000-000000000083", "integration_credentials:manage", "Gestionar credenciales de integraciones"),
    ("40000000-0000-0000-0000-000000000084", "evidence:read", "Leer evidencia externa de entidades"),
]

_READER_ROLES = ("owner", "admin", "member", "viewer", "ai_engineer", "data_engineer", "developer", "analyst")
_MANAGER_ROLES = ("owner", "admin", "member")
_OWNER_ROLES = ("owner", "admin")


# Seed del catálogo (BYOC: cada tenant conecta sus credenciales; sin acceso a
# proveedores reales de forma ilegal. demo_echo es para dev/tests/offline).
_SEED_INTEGRATIONS = [
    {
        "slug": "sunat",
        "name": "SUNAT — Perú",
        "provider": "SUNAT (contribuyente)",
        "version": 1,
        "description": "Consulta y valida información tributaria: estado, condición y datos del contribuyente.",
        "category": "government",
        "logo_ref": "sunat",
        "countries": ["PE"],
        "auth_modes": ["BYOC", "API_KEY", "CERT"],
        "scopes": ["taxpayer:read"],
        "pricing": {"model": "BYOC_NO_MARKUP", "note": "Según contrato/proveedor configurado por el tenant"},
        "rate_limits": {"default_per_minute": 30, "burst": 10},
        "data_policy": {"retention_days": 90, "purpose_required": False},
        "support": {"level": "community", "contact": "marketplace@zent.dev"},
        "certification": "zent-verified",
        "status": "PUBLISHED",
        "capabilities": [
            {
                "slug": "taxpayer",
                "name": "Taxpayer",
                "description": "Consulta de contribuyentes por RUC",
                "actions": [
                    {
                        "action_id": "peru.taxpayer.lookup",
                        "display_name": "Lookup taxpayer",
                        "description": "Datos de estado/condición de un RUC según el proveedor configurado.",
                        "risk_level": "normal",
                        "read_only": True,
                        "requires_approval": False,
                        "contains_personal_data": False,
                        "sensitive_data_classes": [],
                        "retention_policy": {"ttl_days": 30},
                        "cache_policy": {"allow": True, "ttl_seconds": 3600},
                        "timeout_ms": 5_000,
                        "retry_policy": {"max_attempts": 2},
                        "idempotency_support": False,
                        "cost_model": {"model": "PER_CALL", "units": 1},
                        "input_schema": {
                            "type": "object",
                            "required": ["ruc"],
                            "properties": {"ruc": {"type": "string", "minLength": 8, "maxLength": 11}},
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "legal_name": {"type": "string"},
                                "status": {"type": "string"},
                                "condition": {"type": "string"},
                                "address": {"type": ["string", "null"]},
                                "source": {"type": "string"},
                                "retrieved_at": {"type": "string"},
                            },
                        },
                        "provider_config": {
                            "kind": "rest",
                            "method": "GET",
                            "path_template": "/contribuyente/{ruc}",
                            "output_map": {
                                "legal_name": "razonSocial",
                                "status": "estado",
                                "condition": "condicion",
                                "address": "domicilio",
                            },
                        },
                    }
                ],
            }
        ],
    },
    {
        "slug": "reniec-verification",
        "name": "RENIEC — Verificación de identidad",
        "provider": "RENIEC (bajo convenio autorizado)",
        "version": 1,
        "description": "Verificación de identidad SOLO bajo contrato/autorización del tenant y propósito declarado.",
        "category": "government",
        "logo_ref": "reniec",
        "countries": ["PE"],
        "auth_modes": ["BYOC", "PARTNER_MANAGED", "CERT"],
        "scopes": ["identity:verify"],
        "pricing": {"model": "PER_CALL", "note": "Según convenio del tenant con la entidad"},
        "rate_limits": {"default_per_minute": 10},
        "data_policy": {
            "retention_days": 30,
            "purpose_required": True,
            "legal_basis_required": True,
            "personal_data": True,
        },
        "support": {"level": "partner", "contact": "identity@zent.dev"},
        "certification": "privacy-reviewed",
        "status": "PUBLISHED",
        "capabilities": [
            {
                "slug": "identity",
                "name": "Identity verification",
                "description": "Verificación de identidad (DNI) con propósito y base legal",
                "actions": [
                    {
                        "action_id": "peru.identity.verify",
                        "display_name": "Verify identity",
                        "description": "Verifica identidad de una persona natural según el contrato del tenant.",
                        "risk_level": "elevated",
                        "read_only": True,
                        "requires_approval": True,
                        "contains_personal_data": True,
                        "sensitive_data_classes": ["dni", "full_name"],
                        "retention_policy": {"ttl_days": 30, "purpose_required": True},
                        "cache_policy": {"allow": False},
                        "timeout_ms": 6_000,
                        "retry_policy": {"max_attempts": 1},
                        "idempotency_support": True,
                        "cost_model": {"model": "PER_CALL", "units": 1},
                        "input_schema": {
                            "type": "object",
                            "required": ["dni", "purpose"],
                            "properties": {
                                "dni": {"type": "string", "minLength": 8, "maxLength": 8},
                                "purpose": {"type": "string"},
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "verified": {"type": "boolean"},
                                "full_name": {"type": ["string", "null"]},
                                "status": {"type": "string"},
                                "source": {"type": "string"},
                                "retrieved_at": {"type": "string"},
                            },
                        },
                        "provider_config": {
                            "kind": "rest",
                            "method": "GET",
                            "path_template": "/persons/{dni}",
                            "output_map": {
                                "verified": "verified",
                                "full_name": "nombres",
                                "status": "estado",
                            },
                        },
                    }
                ],
            }
        ],
    },
    {
        "slug": "rates-currency",
        "name": "Currency rates",
        "provider": "Proveedor de tasas configurable (BYOC)",
        "version": 1,
        "description": "Tasa de cambio actual de un par de monedas usando el endpoint que el tenant conecte.",
        "category": "finance",
        "logo_ref": "currency",
        "countries": [],
        "auth_modes": ["BYOC", "API_KEY"],
        "scopes": ["fx:read"],
        "pricing": {"model": "FREE"},
        "rate_limits": {"default_per_minute": 60},
        "data_policy": {"retention_days": 7, "purpose_required": False},
        "support": {"level": "community"},
        "certification": "zent-verified",
        "status": "PUBLISHED",
        "capabilities": [
            {
                "slug": "exchange",
                "name": "Exchange rates",
                "description": "Tasa de cambio actual",
                "actions": [
                    {
                        "action_id": "currency.current_rate",
                        "display_name": "Current rate",
                        "description": "Tasa actual para un par de monedas.",
                        "risk_level": "info",
                        "read_only": True,
                        "requires_approval": False,
                        "contains_personal_data": False,
                        "sensitive_data_classes": [],
                        "retention_policy": {"ttl_days": 7},
                        "cache_policy": {"allow": True, "ttl_seconds": 300},
                        "timeout_ms": 4_000,
                        "retry_policy": {"max_attempts": 2},
                        "idempotency_support": False,
                        "cost_model": {"model": "FREE", "units": 0},
                        "input_schema": {
                            "type": "object",
                            "required": ["base", "quote"],
                            "properties": {
                                "base": {"type": "string", "minLength": 3, "maxLength": 3},
                                "quote": {"type": "string", "minLength": 3, "maxLength": 3},
                            },
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "rate": {"type": "number"},
                                "base": {"type": "string"},
                                "quote": {"type": "string"},
                                "retrieved_at": {"type": "string"},
                            },
                        },
                        "provider_config": {
                            "kind": "rest",
                            "method": "GET",
                            "path_template": "/rates/{base}/{quote}",
                            "output_map": {"rate": "rate", "base": "base", "quote": "quote"},
                        },
                    }
                ],
            }
        ],
    },
    {
        "slug": "demo-echo",
        "name": "Demo Echo",
        "provider": "Zent (desarrollo)",
        "version": 1,
        "description": "Integración de prueba: devuelve lo que recibe. Sin red ni credenciales.",
        "category": "data",
        "logo_ref": "echo",
        "countries": [],
        "auth_modes": ["NONE"],
        "scopes": ["echo:read"],
        "pricing": {"model": "FREE"},
        "rate_limits": {"default_per_minute": 120},
        "data_policy": {"retention_days": 1, "purpose_required": False},
        "support": {"level": "internal"},
        "certification": "none",
        "status": "PUBLISHED",
        "capabilities": [
            {
                "slug": "echo",
                "name": "Echo",
                "description": "Devuelve los inputs recibidos",
                "actions": [
                    {
                        "action_id": "demo.echo",
                        "display_name": "Echo input",
                        "description": "Devuelve el texto recibido (para probar el runtime sin proveedor).",
                        "risk_level": "info",
                        "read_only": True,
                        "requires_approval": False,
                        "contains_personal_data": False,
                        "sensitive_data_classes": [],
                        "retention_policy": {"ttl_days": 1},
                        "cache_policy": {"allow": False},
                        "timeout_ms": 2_000,
                        "retry_policy": {"max_attempts": 1},
                        "idempotency_support": False,
                        "cost_model": {"model": "FREE", "units": 0},
                        "input_schema": {
                            "type": "object",
                            "required": ["text"],
                            "properties": {"text": {"type": "string", "maxLength": 500}},
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"echo": {"type": "string"}},
                        },
                        "provider_config": {"kind": "demo_echo"},
                    }
                ],
            }
        ],
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_manifests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(80) NOT NULL UNIQUE,
            name VARCHAR(150) NOT NULL,
            provider VARCHAR(150) NOT NULL,
            version INT NOT NULL DEFAULT 1,
            description TEXT,
            category VARCHAR(40) NOT NULL DEFAULT 'data',
            logo_ref VARCHAR(120),
            countries JSONB NOT NULL DEFAULT '[]',
            auth_modes JSONB NOT NULL DEFAULT '[]',
            scopes JSONB NOT NULL DEFAULT '[]',
            pricing JSONB NOT NULL DEFAULT '{}',
            rate_limits JSONB NOT NULL DEFAULT '{}',
            data_policy JSONB NOT NULL DEFAULT '{}',
            support JSONB NOT NULL DEFAULT '{}',
            certification VARCHAR(60),
            status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_capabilities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id UUID NOT NULL REFERENCES integration_manifests(id) ON DELETE CASCADE,
            slug VARCHAR(80) NOT NULL,
            name VARCHAR(120) NOT NULL,
            description TEXT,
            UNIQUE (integration_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            integration_id UUID NOT NULL REFERENCES integration_manifests(id) ON DELETE CASCADE,
            capability_slug VARCHAR(80) NOT NULL,
            action_id VARCHAR(120) NOT NULL UNIQUE,
            display_name VARCHAR(120) NOT NULL,
            description TEXT,
            input_schema JSONB NOT NULL DEFAULT '{"type":"object","properties":{}}',
            output_schema JSONB NOT NULL DEFAULT '{"type":"object","properties":{}}',
            risk_level VARCHAR(20) NOT NULL DEFAULT 'info',
            read_only BOOLEAN NOT NULL DEFAULT true,
            requires_approval BOOLEAN NOT NULL DEFAULT false,
            contains_personal_data BOOLEAN NOT NULL DEFAULT false,
            sensitive_data_classes JSONB NOT NULL DEFAULT '[]',
            retention_policy JSONB NOT NULL DEFAULT '{}',
            cache_policy JSONB NOT NULL DEFAULT '{}',
            timeout_ms INT NOT NULL DEFAULT 5000,
            retry_policy JSONB NOT NULL DEFAULT '{}',
            idempotency_support BOOLEAN NOT NULL DEFAULT false,
            cost_model JSONB NOT NULL DEFAULT '{}',
            provider_config JSONB NOT NULL DEFAULT '{}',
            version INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS installed_integrations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
            integration_id UUID NOT NULL REFERENCES integration_manifests(id) ON DELETE CASCADE,
            version INT NOT NULL DEFAULT 1,
            credential_ref VARCHAR(160),
            status VARCHAR(20) NOT NULL DEFAULT 'installed',
            enabled_actions JSONB NOT NULL DEFAULT '[]',
            auto_use_policy JSONB NOT NULL DEFAULT '{}',
            spend_limit JSONB NOT NULL DEFAULT '{}',
            purpose VARCHAR(80),
            legal_basis_reference VARCHAR(200),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_installed_integrations_org "
        "ON installed_integrations(organization_id, workspace_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_credentials (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
            integration_id UUID NOT NULL REFERENCES integration_manifests(id) ON DELETE CASCADE,
            install_id UUID NOT NULL REFERENCES installed_integrations(id) ON DELETE CASCADE,
            auth_mode VARCHAR(30) NOT NULL DEFAULT 'BYOC',
            cred_type VARCHAR(30) NOT NULL DEFAULT 'API_KEY',
            status VARCHAR(20) NOT NULL DEFAULT 'configured',
            provider_account_id VARCHAR(160),
            refreshed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_usage_ledger (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            integration_id UUID NOT NULL,
            install_id UUID,
            action_id VARCHAR(120) NOT NULL,
            units INT NOT NULL DEFAULT 0,
            provider_cost NUMERIC(14,4) NOT NULL DEFAULT 0,
            customer_cost NUMERIC(14,4) NOT NULL DEFAULT 0,
            currency VARCHAR(3) NOT NULL DEFAULT 'PEN',
            workflow_id UUID,
            run_id UUID,
            agent_run_id UUID,
            purpose VARCHAR(80),
            status VARCHAR(20) NOT NULL DEFAULT 'ok',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_ledger_org_time "
        "ON integration_usage_ledger(organization_id, workspace_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS integration_budget_counters (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            install_id UUID NOT NULL,
            action_id VARCHAR(120),
            scope VARCHAR(20) NOT NULL,
            bucket VARCHAR(120) NOT NULL,
            cost NUMERIC(14,4) NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, workspace_id, install_id, action_id, scope, bucket)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS external_evidence (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            integration_id UUID NOT NULL,
            install_id UUID,
            action_id VARCHAR(120) NOT NULL,
            entity_type VARCHAR(60) NOT NULL,
            entity_id VARCHAR(120) NOT NULL,
            provider VARCHAR(150) NOT NULL,
            purpose VARCHAR(80),
            retrieved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            freshness_ttl_seconds INT NOT NULL DEFAULT 3600,
            input_hash VARCHAR(64) NOT NULL,
            output JSONB NOT NULL DEFAULT '{}',
            provenance JSONB NOT NULL DEFAULT '{}',
            workflow_id UUID,
            run_id UUID,
            agent_run_id UUID,
            cost NUMERIC(14,4) NOT NULL DEFAULT 0,
            retention_until TIMESTAMPTZ,
            status VARCHAR(20) NOT NULL DEFAULT 'fresh'
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_external_evidence_entity "
        "ON external_evidence(organization_id, workspace_id, entity_type, entity_id, retrieved_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_external_evidence_cache "
        "ON external_evidence(organization_id, workspace_id, install_id, action_id, input_hash)"
    )

    # --- Permisos + roles ------------------------------------------------
    for pid, code, desc in _MARKET_PERMISSIONS:
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

    _grant("marketplace:read", _READER_ROLES)
    _grant("marketplace:install", _MANAGER_ROLES)
    _grant("marketplace:manage", _MANAGER_ROLES)
    _grant("integration_credentials:manage", _OWNER_ROLES)
    _grant("evidence:read", _READER_ROLES)

    # --- Seed catálogo ----------------------------------------------------
    for integ in _SEED_INTEGRATIONS:
        row = bind.execute(
            text(
                "SELECT id FROM integration_manifests WHERE slug = :slug"
            ),
            {"slug": integ["slug"]},
        ).fetchone()
        if row is not None:
            continue
        mid = bind.execute(
            text(
                "INSERT INTO integration_manifests "
                "(slug, name, provider, version, description, category, logo_ref, countries, "
                "auth_modes, scopes, pricing, rate_limits, data_policy, support, certification, status) "
                "VALUES (:slug, :name, :provider, :ver, :desc, :cat, :logo, CAST(:countries AS jsonb), "
                "CAST(:auth AS jsonb), CAST(:scopes AS jsonb), CAST(:pricing AS jsonb), "
                "CAST(:rl AS jsonb), CAST(:dp AS jsonb), CAST(:support AS jsonb), :cert, :status) "
                "RETURNING id"
            ),
            {
                "slug": integ["slug"],
                "name": integ["name"],
                "provider": integ["provider"],
                "ver": int(integ["version"]),
                "desc": integ["description"],
                "cat": integ["category"],
                "logo": integ["logo_ref"],
                "countries": json.dumps(integ["countries"]),
                "auth": json.dumps(integ["auth_modes"]),
                "scopes": json.dumps(integ["scopes"]),
                "pricing": json.dumps(integ["pricing"]),
                "rl": json.dumps(integ["rate_limits"]),
                "dp": json.dumps(integ["data_policy"]),
                "support": json.dumps(integ["support"]),
                "cert": integ["certification"],
                "status": integ["status"],
            },
        ).scalar()
        for cap in integ["capabilities"]:
            cap_row = bind.execute(
                text(
                    "INSERT INTO integration_capabilities (integration_id, slug, name, description) "
                    "VALUES (:iid, :slug, :name, :desc) RETURNING id"
                ),
                {"iid": mid, "slug": cap["slug"], "name": cap["name"], "desc": cap["description"]},
            ).scalar()
            for act in cap["actions"]:
                bind.execute(
                    text(
                        "INSERT INTO integration_actions "
                        "(integration_id, capability_slug, action_id, display_name, description, "
                        "input_schema, output_schema, risk_level, read_only, requires_approval, "
                        "contains_personal_data, sensitive_data_classes, retention_policy, cache_policy, "
                        "timeout_ms, retry_policy, idempotency_support, cost_model, provider_config) "
                        "VALUES (:iid, :cap, :aid, :dn, :desc, CAST(:ins AS jsonb), CAST(:outs AS jsonb), "
                        ":risk, :ro, :ra, :pd, CAST(:sdc AS jsonb), CAST(:rp AS jsonb), CAST(:cp AS jsonb), "
                        ":tmo, CAST(:retry AS jsonb), :idem, CAST(:cost AS jsonb), CAST(:pc AS jsonb)) "
                        "ON CONFLICT (action_id) DO NOTHING"
                    ),
                    {
                        "iid": mid,
                        "cap": cap["slug"],
                        "aid": act["action_id"],
                        "dn": act["display_name"],
                        "desc": act["description"],
                        "ins": json.dumps(act["input_schema"]),
                        "outs": json.dumps(act["output_schema"]),
                        "risk": act["risk_level"],
                        "ro": bool(act["read_only"]),
                        "ra": bool(act["requires_approval"]),
                        "pd": bool(act["contains_personal_data"]),
                        "sdc": json.dumps(act["sensitive_data_classes"]),
                        "rp": json.dumps(act["retention_policy"]),
                        "cp": json.dumps(act["cache_policy"]),
                        "tmo": int(act["timeout_ms"]),
                        "retry": json.dumps(act["retry_policy"]),
                        "idem": bool(act["idempotency_support"]),
                        "cost": json.dumps(act["cost_model"]),
                        "pc": json.dumps(act.get("provider_config") or {}),
                    },
                )
                _ = cap_row


def downgrade() -> None:
    for table in (
        "external_evidence",
        "integration_budget_counters",
        "integration_usage_ledger",
        "integration_credentials",
        "installed_integrations",
        "integration_actions",
        "integration_capabilities",
        "integration_manifests",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for pid, _code, _desc in _MARKET_PERMISSIONS:
        op.execute(text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})

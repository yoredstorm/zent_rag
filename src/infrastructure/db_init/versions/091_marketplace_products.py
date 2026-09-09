"""Phase 33A — Marketplace Factory: producto unificado, versiones,
dependencias, instalaciones y proveedores.

Revision ID: 091
Revises: 090
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "091"
down_revision: str = "090"
branch_labels = None
depends_on = None

_FACTORY_PERMISSIONS = [
    ("40000000-0000-0000-0000-000000000100", "marketplace_factory:manage", "Fabricar y publicar productos (Control Center)"),
    ("40000000-0000-0000-0000-000000000101", "marketplace_products:read", "Leer catálogo de productos"),
]

_CC_ROLES = ("super_admin", "platform_admin", "operations")
_TENANT_ROLES = ("owner", "admin", "member", "viewer", "ai_engineer", "data_engineer", "developer", "analyst")

PRODUCT_STATUSES = (
    "DRAFT", "INTERNAL_TEST", "SECURITY_REVIEW", "PRODUCT_REVIEW", "READY",
    "PUBLISHED", "PAUSED", "DEPRECATED", "END_OF_LIFE",
)
PRODUCT_TYPES = (
    "INTEGRATION", "WORKFLOW_TEMPLATE", "AGENT_TEMPLATE", "INTELLIGENCE_PACK",
    "BUSINESS_PACK", "SEMANTIC_PACK", "COMPOSITE_PACK",
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_providers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(80) NOT NULL UNIQUE,
            name VARCHAR(150) NOT NULL,
            legal_entity VARCHAR(200),
            contact JSONB NOT NULL DEFAULT '{}',
            support_sla VARCHAR(200),
            contracts JSONB NOT NULL DEFAULT '{}',
            allowed_countries JSONB NOT NULL DEFAULT '[]',
            status VARCHAR(30) NOT NULL DEFAULT 'ACTIVE',
            revenue_share INT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_products (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(100) NOT NULL UNIQUE,
            name VARCHAR(180) NOT NULL,
            short_description TEXT,
            long_description TEXT,
            product_type VARCHAR(40) NOT NULL DEFAULT 'INTEGRATION',
            publisher UUID REFERENCES marketplace_providers(id) ON DELETE SET NULL,
            version INT NOT NULL DEFAULT 1,
            status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
            category VARCHAR(60) NOT NULL DEFAULT 'data',
            subcategories JSONB NOT NULL DEFAULT '[]',
            tags JSONB NOT NULL DEFAULT '[]',
            countries JSONB NOT NULL DEFAULT '[]',
            industries JSONB NOT NULL DEFAULT '[]',
            logo VARCHAR(255),
            screenshots JSONB NOT NULL DEFAULT '[]',
            documentation VARCHAR(500),
            pricing JSONB NOT NULL DEFAULT '{}',
            entitlements JSONB NOT NULL DEFAULT '{}',
            dependencies JSONB NOT NULL DEFAULT '[]',
            included_assets JSONB NOT NULL DEFAULT '[]',
            installation_flow JSONB NOT NULL DEFAULT '[]',
            configuration_schema JSONB NOT NULL DEFAULT '{}',
            result_surfaces JSONB NOT NULL DEFAULT '[]',
            support JSONB NOT NULL DEFAULT '{}',
            security JSONB NOT NULL DEFAULT '{}',
            privacy JSONB NOT NULL DEFAULT '{}',
            certification VARCHAR(60),
            release_notes JSONB NOT NULL DEFAULT '[]',
            rollout JSONB NOT NULL DEFAULT '{}',
            featured JSONB NOT NULL DEFAULT '{}',
            collections JSONB NOT NULL DEFAULT '[]',
            legacy_source VARCHAR(40),
            legacy_ref VARCHAR(160),
            published_at TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_products_type_status "
        "ON marketplace_products(product_type, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_product_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES marketplace_products(id) ON DELETE CASCADE,
            version INT NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
            payload JSONB NOT NULL DEFAULT '{}',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            released_at TIMESTAMPTZ,
            UNIQUE (product_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_product_dependencies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            product_id UUID NOT NULL REFERENCES marketplace_products(id) ON DELETE CASCADE,
            kind VARCHAR(40) NOT NULL,
            ref VARCHAR(160) NOT NULL,
            requirement VARCHAR(20) NOT NULL DEFAULT 'required',
            alias VARCHAR(80),
            UNIQUE (product_id, kind, ref)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_product_installations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
            product_id UUID NOT NULL REFERENCES marketplace_products(id) ON DELETE CASCADE,
            product_version INT NOT NULL DEFAULT 1,
            status VARCHAR(30) NOT NULL DEFAULT 'installed',
            install_answers JSONB NOT NULL DEFAULT '{}',
            installed_assets JSONB NOT NULL DEFAULT '{}',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, workspace_id, product_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_market_installations_org "
        "ON marketplace_product_installations(organization_id, workspace_id, created_at DESC)"
    )

    for pid, code, desc in _FACTORY_PERMISSIONS:
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

    _grant("marketplace_factory:manage", _CC_ROLES)
    _grant("marketplace_products:read", _TENANT_ROLES)


def downgrade() -> None:
    for table in (
        "marketplace_product_installations",
        "marketplace_product_dependencies",
        "marketplace_product_versions",
        "marketplace_products",
        "marketplace_providers",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for pid, _code, _desc in _FACTORY_PERMISSIONS:
        op.execute(text("DELETE FROM permissions WHERE id = :pid"), {"pid": pid})

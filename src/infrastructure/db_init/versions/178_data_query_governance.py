"""P19.1-01 - gobierno de publicacion de consultas y minimo privilegio.

Revision ID: 178
Revises: 177

Aditiva. Separa la autoridad de editar workflows de la autoridad de publicar
acceso a datos. Sin politica explicita por conector/workspace no se publica
ninguna tabla ni columna. Las politicas y los eventos de publicacion son
append-only/versionados; no se amplian accesos existentes.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision: str = "178"
down_revision: str = "177"
branch_labels = None
depends_on = None

_PERMISSIONS = [
    ("40000000-0000-0000-0000-000000000073", "data_sources:discover", "Descubrir fuentes y esquemas fisicos"),
    ("40000000-0000-0000-0000-000000000074", "data_queries:publish", "Publicar consultas autorizadas"),
    ("40000000-0000-0000-0000-000000000075", "data_queries:publish_sensitive", "Publicar columnas sensibles con proposito"),
    ("40000000-0000-0000-0000-000000000076", "data_queries:read", "Ver consultas publicadas"),
    ("40000000-0000-0000-0000-000000000077", "data_queries:preview", "Previsualizar consultas con datos redactados"),
    ("40000000-0000-0000-0000-000000000078", "data_queries:manage", "Administrar politicas de publicacion de datos"),
]

_READ = ("owner", "admin", "member", "viewer", "ai_engineer", "data_engineer", "developer", "analyst")
_DISCOVER = ("owner", "admin", "member", "data_engineer", "developer", "analyst")
_PREVIEW = ("owner", "admin", "member", "data_engineer", "developer", "analyst")
_PUBLISH = ("owner", "admin", "data_engineer")
_MANAGE = ("owner", "admin")
_SENSITIVE = ("owner",)

_GRANTS = {
    "data_sources:discover": _DISCOVER,
    "data_queries:read": _READ,
    "data_queries:preview": _PREVIEW,
    "data_queries:publish": _PUBLISH,
    "data_queries:manage": _MANAGE,
    "data_queries:publish_sensitive": _SENSITIVE,
}


def upgrade() -> None:
    bind = op.get_bind()
    for pid, code, description in _PERMISSIONS:
        bind.execute(
            text(
                "INSERT INTO permissions (id, code, description) VALUES (:pid, :code, :description) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"pid": pid, "code": code, "description": description},
        )

    def _grant(permission: str, roles: tuple[str, ...]) -> None:
        role_list = ", ".join(f"'{role}'" for role in roles)
        bind.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
                f"WHERE r.organization_id IS NULL AND r.name IN ({role_list}) "
                "AND p.code = :permission ON CONFLICT DO NOTHING"
            ),
            {"permission": permission},
        )

    for permission, roles in _GRANTS.items():
        _grant(permission, roles)

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_query_publication_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            connector_ref UUID NOT NULL,
            policy JSONB NOT NULL DEFAULT '{}'::jsonb,
            policy_hash VARCHAR(64) NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, workspace_id, connector_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_publication_policies_org_ws "
        "ON data_query_publication_policies(organization_id, workspace_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS data_query_publication_events (
            id BIGSERIAL PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            actor_id UUID,
            action VARCHAR(40) NOT NULL,
            connector_ref UUID,
            binding_id UUID,
            capability_ref VARCHAR(120),
            resource_ref VARCHAR(200),
            selected_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
            sensitive_columns JSONB NOT NULL DEFAULT '[]'::jsonb,
            purpose VARCHAR(300),
            policy_hash VARCHAR(64),
            plan_hash VARCHAR(64),
            previous_binding_id UUID,
            approval_id UUID,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_publication_events_org_created "
        "ON data_query_publication_events(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_data_publication_events_binding "
        "ON data_query_publication_events(binding_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_query_publication_events")
    op.execute("DROP TABLE IF EXISTS data_query_publication_policies")
    bind = op.get_bind()
    codes = [code for _, code, _ in _PERMISSIONS]
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = ANY(:codes))"),
        {"codes": codes},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = ANY(:codes)"), {"codes": codes})

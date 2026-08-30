"""Multi-tenant organizations + RBAC + platform resources.

Revision ID: 003
Revises: 002
Create Date: 2026-08-19

Renombra tenants -> organizations (con tenant_id -> organization_id en todas las
tablas de plataforma), crea el modelo RBAC (roles, permissions, role_permissions,
memberships), migra api_tokens -> api_keys (organización-scoped) y crea los
recursos de plataforma (projects, knowledge_bases, agents, connectors, audit_logs).

Los scripts SQL de db_init/ (que corren solo en bases nuevas) ya contienen el
esquema final; esta migración transforma bases existentes.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tablas con columna tenant_id -> organization_id (no incluye api_tokens, que se migra aparte)
_COLUMN_RENAMES = {
    "users": "tenant_id",
    "rate_limit_counters": "tenant_id",
    "usage_logs": "tenant_id",
    "query_audit_log": "tenant_id",
    "documents": "tenant_id",
    "subscriptions": "tenant_id",
    "rag_evaluations": "tenant_id",  # puede no existir si nunca se creó en runtime
}

_INDEX_RENAMES = [
    ("idx_users_tenant_id", "idx_users_organization_id"),
    ("idx_usage_logs_tenant_id", "idx_usage_logs_organization_id"),
    ("idx_query_audit_tenant", "idx_query_audit_organization"),
    ("idx_documents_tenant", "idx_documents_organization"),
    ("idx_subscriptions_tenant", "idx_subscriptions_organization"),
    ("uq_subscriptions_active_tenant", "uq_subscriptions_active_organization"),
    ("idx_rag_evals_tenant", "idx_rag_evals_organization"),
]

_RBAC_TABLES = [
    # roles
    """
    CREATE TABLE IF NOT EXISTS roles (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT,
        is_system BOOLEAN NOT NULL DEFAULT false,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS permissions (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        code VARCHAR(100) NOT NULL UNIQUE,
        description TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS role_permissions (
        role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
        permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
        PRIMARY KEY (role_id, permission_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memberships (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role_id UUID NOT NULL REFERENCES roles(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, user_id)
    )
    """,
]

_RESOURCE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_bases (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'archived')),
        embedding_model VARCHAR(100),
        config_json JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agents (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        system_prompt TEXT,
        tools JSONB DEFAULT '[]',
        model VARCHAR(100),
        config_json JSONB DEFAULT '{}',
        is_active BOOLEAN NOT NULL DEFAULT true,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS connectors (
        id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
        name VARCHAR(255) NOT NULL,
        type VARCHAR(20) NOT NULL CHECK (type IN ('sql', 'api', 'files')),
        config_json JSONB DEFAULT '{}',
        status VARCHAR(20) NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'disabled', 'error')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (organization_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id BIGSERIAL PRIMARY KEY,
        organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
        actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        action VARCHAR(100) NOT NULL,
        resource_type VARCHAR(100) NOT NULL,
        resource_id VARCHAR(255),
        ip_address VARCHAR(45),
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


def upgrade() -> None:
    # NOTA: en bases NUEVAS los scripts de db_init/ ya crean el esquema final
    # (organizations, api_keys, ...). Esta migración es idempotente: cada paso
    # verifica existencia antes de tocar (funciona en bases legacy y frescas).
    #
    # 1. Rename tabla tenants -> organizations (solo si existe la legacy)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'tenants' AND table_schema = current_schema()
            ) THEN
                ALTER TABLE tenants RENAME TO organizations;
            END IF;
        END $$;
        """
    )
    # Clean break: el API key legacy (api_key_hash en organizations) deja de
    # existir; los keys viven en api_keys con hash SHA-256.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'organizations' AND column_name = 'api_key_hash'
            ) THEN
                ALTER TABLE organizations DROP COLUMN api_key_hash;
            END IF;
        END $$;
        """
    )
    for index_old, index_new in _INDEX_RENAMES:
        op.execute(f"ALTER INDEX IF EXISTS {index_old} RENAME TO {index_new}")

    # 2. Rename columnas tenant_id -> organization_id
    for table, col in _COLUMN_RENAMES.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = '{col}'
                ) THEN
                    EXECUTE 'ALTER TABLE {table} RENAME COLUMN {col} TO organization_id';
                END IF;
            END $$;
            """
        )

    # 3. Migrar api_tokens -> api_keys (organization-scoped) — solo si existe legacy
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL DEFAULT 'Default',
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            key_prefix VARCHAR(16) NOT NULL,
            scopes JSONB NOT NULL DEFAULT '["rag:query", "rag:ingest"]'::jsonb,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            last_used_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'api_tokens' AND table_schema = current_schema()
            ) THEN
                INSERT INTO api_keys (id, organization_id, name, key_hash, key_prefix,
                                      scopes, is_active, last_used_at, expires_at, created_at)
                SELECT t.id, s.organization_id, t.name, t.token_hash, t.token_prefix,
                       t.scopes, t.is_active, t.last_used_at, t.expires_at, t.created_at
                FROM api_tokens t
                JOIN subscriptions s ON s.id = t.subscription_id
                ON CONFLICT (key_hash) DO NOTHING;
                DROP TABLE api_tokens;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_keys_organization ON api_keys(organization_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_api_keys_active_name "
        "ON api_keys(organization_id, name) WHERE is_active = true"
    )

    # 4. Planes: renombrar columnas legacy de tenant (solo si existen)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'plans' AND column_name = 'max_tenants'
            ) THEN
                ALTER TABLE plans RENAME COLUMN max_tenants TO max_organizations;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'plans' AND column_name = 'max_users_per_tenant'
            ) THEN
                ALTER TABLE plans RENAME COLUMN max_users_per_tenant TO max_users_per_organization;
            END IF;
        END $$;
        """
    )

    # 5. Crear tablas RBAC y recursos
    for ddl in _RBAC_TABLES + _RESOURCE_TABLES:
        op.execute(ddl)

    # 6. Seeds de roles/permissions/role_permissions
    op.execute(
        """
        INSERT INTO roles (id, organization_id, name, description, is_system) VALUES
            ('50000000-0000-0000-0000-000000000001', NULL, 'owner',
             'Dueño de la organización. Control total incluyendo billing y API keys.', true),
            ('50000000-0000-0000-0000-000000000002', NULL, 'admin',
             'Administrador: gestiona recursos, usuarios y configuración.', true),
            ('50000000-0000-0000-0000-000000000003', NULL, 'member',
             'Miembro: usa RAG, crea y edita recursos de su proyecto.', true),
            ('50000000-0000-0000-0000-000000000004', NULL, 'viewer',
             'Solo lectura: consulta RAG y ve configuración.', true)
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000001', 'org:read', 'Ver datos de la organización'),
            ('40000000-0000-0000-0000-000000000002', 'org:write', 'Modificar datos de la organización'),
            ('40000000-0000-0000-0000-000000000003', 'users:read', 'Listar usuarios y roles'),
            ('40000000-0000-0000-0000-000000000004', 'users:write', 'Invitar/eliminar usuarios y cambiar roles'),
            ('40000000-0000-0000-0000-000000000005', 'apikeys:read', 'Ver API keys'),
            ('40000000-0000-0000-0000-000000000006', 'apikeys:write', 'Crear/rotar/revocar API keys'),
            ('40000000-0000-0000-0000-000000000007', 'projects:read', 'Ver proyectos'),
            ('40000000-0000-0000-0000-000000000008', 'projects:write', 'Crear/editar/borrar proyectos'),
            ('40000000-0000-0000-0000-000000000009', 'kbs:read', 'Ver knowledge bases'),
            ('40000000-0000-0000-0000-000000000010', 'kbs:write', 'Crear/editar/borrar knowledge bases'),
            ('40000000-0000-0000-0000-000000000011', 'agents:read', 'Ver agentes'),
            ('40000000-0000-0000-0000-000000000012', 'agents:write', 'Crear/editar/borrar agentes'),
            ('40000000-0000-0000-0000-000000000013', 'connectors:read', 'Ver conectores'),
            ('40000000-0000-0000-0000-000000000014', 'connectors:write', 'Crear/editar/borrar conectores'),
            ('40000000-0000-0000-0000-000000000015', 'usage:read', 'Ver métricas de uso'),
            ('40000000-0000-0000-0000-000000000016', 'billing:read', 'Ver suscripción y cuota'),
            ('40000000-0000-0000-0000-000000000017', 'billing:write', 'Gestionar plan y facturación'),
            ('40000000-0000-0000-0000-000000000018', 'audit:read', 'Leer audit logs de la organización'),
            ('40000000-0000-0000-0000-000000000019', 'rag:query', 'Ejecutar consultas RAG'),
            ('40000000-0000-0000-0000-000000000020', 'rag:ingest', 'Sincronizar datos (ingestion)')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'owner'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'admin'
          AND p.code <> 'billing:write'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'member'
          AND p.code IN (
            'org:read', 'users:read', 'apikeys:read',
            'projects:read', 'projects:write',
            'kbs:read', 'kbs:write',
            'agents:read', 'agents:write',
            'connectors:read', 'connectors:write',
            'usage:read', 'billing:read', 'audit:read', 'rag:query', 'rag:ingest')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'viewer'
          AND p.code IN (
            'org:read', 'users:read', 'apikeys:read',
            'projects:read', 'kbs:read', 'agents:read', 'connectors:read',
            'usage:read', 'billing:read', 'audit:read', 'rag:query')
        ON CONFLICT DO NOTHING
        """
    )

    # 7. Backfill de memberships desde users
    op.execute(
        """
        INSERT INTO memberships (organization_id, user_id, role_id)
        SELECT u.organization_id, u.id, r.id
        FROM users u
        JOIN roles r ON r.organization_id IS NULL AND r.name = 'owner'
        WHERE u.external_id = 'default-admin'
          AND u.organization_id IS NOT NULL
        ON CONFLICT (organization_id, user_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO memberships (organization_id, user_id, role_id)
        SELECT u.organization_id, u.id,
               CASE WHEN u.role = 'admin' THEN
                 (SELECT id FROM roles WHERE organization_id IS NULL AND name = 'admin')
               ELSE
                 (SELECT id FROM roles WHERE organization_id IS NULL AND name = 'member')
               END
        FROM users u
        WHERE u.organization_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM memberships m
            WHERE m.user_id = u.id AND m.organization_id = u.organization_id
        )
        """
    )

    # 8. Índices de las tablas nuevas
    for idx in (
        "CREATE INDEX IF NOT EXISTS idx_projects_organization ON projects(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_kbs_organization ON knowledge_bases(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_agents_organization ON agents(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_connectors_organization ON connectors(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_organization "
        "ON audit_logs(organization_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_memberships_organization ON memberships(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_memberships_user ON memberships(user_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_system_name "
        "ON roles(name) WHERE organization_id IS NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_org_name "
        "ON roles(organization_id, name) WHERE organization_id IS NOT NULL",
    ):
        op.execute(idx)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS connectors")
    op.execute("DROP TABLE IF EXISTS agents")
    op.execute("DROP TABLE IF EXISTS knowledge_bases")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS memberships")
    op.execute("DROP TABLE IF EXISTS role_permissions")
    op.execute("DROP TABLE IF EXISTS permissions")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute(
        "CREATE TABLE IF NOT EXISTS api_tokens ("
        "id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),"
        "subscription_id UUID NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,"
        "token_hash VARCHAR(64) NOT NULL UNIQUE,"
        "token_prefix VARCHAR(16) NOT NULL,"
        "name VARCHAR(255) NOT NULL DEFAULT 'Default',"
        "scopes JSONB NOT NULL DEFAULT '[\"rag:query\", \"rag:ingest\"]'::jsonb,"
        "is_active BOOLEAN NOT NULL DEFAULT true,"
        "last_used_at TIMESTAMPTZ,"
        "expires_at TIMESTAMPTZ,"
        "created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"
    )
    op.execute("ALTER TABLE plans RENAME COLUMN max_organizations TO max_tenants")
    op.execute("ALTER TABLE plans RENAME COLUMN max_users_per_organization TO max_users_per_tenant")
    op.execute("ALTER TABLE organizations RENAME TO tenants")

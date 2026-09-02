"""Platform RBAC — roles de plataforma granulares + roles de tenant nuevos.

Revision ID: 023
Revises: 022
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # Platform roles (Control Center): separados del RBAC de tenant.
    # -------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_roles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name VARCHAR(100) NOT NULL UNIQUE,
            description TEXT,
            is_system BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_role_permissions (
            role_id UUID NOT NULL REFERENCES platform_roles(id) ON DELETE CASCADE,
            permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
            PRIMARY KEY (role_id, permission_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_platform_roles (
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role_id UUID NOT NULL REFERENCES platform_roles(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, role_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_platform_roles_user ON user_platform_roles(user_id)"
    )

    # -------------------------------------------------------------------------
    # Catálogo de permisos de plataforma (continúa 40000000-...-031)
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000032', 'tenant.read',
             'Ver tenants (listado y ficha 360)'),
            ('40000000-0000-0000-0000-000000000033', 'tenant.write',
             'Modificar datos de tenants'),
            ('40000000-0000-0000-0000-000000000034', 'tenant.suspend',
             'Pausar/suspender/cancelar tenants'),
            ('40000000-0000-0000-0000-000000000035', 'billing.read',
             'Ver billing global de la plataforma'),
            ('40000000-0000-0000-0000-000000000036', 'billing.manage',
             'Gestionar planes, precios y suscripciones'),
            ('40000000-0000-0000-0000-000000000037', 'models.read',
             'Ver modelos y providers'),
            ('40000000-0000-0000-0000-000000000038', 'models.manage',
             'Gestionar modelos y providers'),
            ('40000000-0000-0000-0000-000000000039', 'operations.read',
             'Ver operaciones (jobs, workers, errores)'),
            ('40000000-0000-0000-0000-000000000040', 'operations.write',
             'Ejecutar operaciones de plataforma'),
            ('40000000-0000-0000-0000-000000000041', 'support.impersonate',
             'Iniciar sesiones de soporte (impersonación)'),
            ('40000000-0000-0000-0000-000000000042', 'audit.read',
             'Ver audit logs globales'),
            ('40000000-0000-0000-0000-000000000043', 'platform.settings.manage',
             'Gestionar configuración de plataforma'),
            ('40000000-0000-0000-0000-000000000044', 'platform.users.manage',
             'Gestionar usuarios y roles de plataforma'),
            ('40000000-0000-0000-0000-000000000045', 'analytics.read',
             'Ver métricas y analítica de plataforma')
        ON CONFLICT (code) DO NOTHING
        """
    )

    # -------------------------------------------------------------------------
    # Seed de 7 roles de plataforma con UUIDs estables
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO platform_roles (id, name, description, is_system) VALUES
            ('60000000-0000-0000-0000-000000000001', 'super_admin',
             'Control total de la plataforma', true),
            ('60000000-0000-0000-0000-000000000002', 'platform_admin',
             'Administra la plataforma salvo settings globales', true),
            ('60000000-0000-0000-0000-000000000003', 'operations',
             'Operaciones: tenants, jobs y monitoreo', true),
            ('60000000-0000-0000-0000-000000000004', 'support',
             'Soporte: lectura de tenants e impersonación', true),
            ('60000000-0000-0000-0000-000000000005', 'finance',
             'Finanzas: billing y analítica económica', true),
            ('60000000-0000-0000-0000-000000000006', 'security_auditor',
             'Auditoría: lectura de tenants y audit logs', true),
            ('60000000-0000-0000-0000-000000000007', 'read_only',
             'Solo lectura operativa de la plataforma', true)
        ON CONFLICT (name) DO NOTHING
        """
    )
    # super_admin: todos los permisos.
    op.execute(
        """
        INSERT INTO platform_role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM platform_roles r CROSS JOIN permissions p
        WHERE r.name = 'super_admin'
        ON CONFLICT DO NOTHING
        """
    )
    # platform_admin: todos salvo platform.settings.manage.
    op.execute(
        """
        INSERT INTO platform_role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM platform_roles r CROSS JOIN permissions p
        WHERE r.name = 'platform_admin' AND p.code <> 'platform.settings.manage'
        ON CONFLICT DO NOTHING
        """
    )
    _PLATFORM_ROLE_PERMS = {
        "operations": (
            "tenant.read", "operations.read", "operations.write", "analytics.read"
        ),
        "support": ("tenant.read", "support.impersonate", "analytics.read"),
        "finance": ("tenant.read", "billing.read", "billing.manage", "analytics.read"),
        "security_auditor": ("tenant.read", "audit.read"),
        "read_only": ("tenant.read", "analytics.read"),
    }
    for role_name, codes in _PLATFORM_ROLE_PERMS.items():
        placeholders = ", ".join(f"'{c}'" for c in codes)
        op.execute(
            f"""
            INSERT INTO platform_role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM platform_roles r JOIN permissions p
            ON p.code IN ({placeholders})
            WHERE r.name = '{role_name}'
            ON CONFLICT DO NOTHING
            """
        )

    # Backfill: usuarios con is_platform_admin legacy → super_admin.
    op.execute(
        """
        INSERT INTO user_platform_roles (user_id, role_id)
        SELECT u.id, r.id FROM users u CROSS JOIN platform_roles r
        WHERE u.is_platform_admin AND r.name = 'super_admin'
        ON CONFLICT DO NOTHING
        """
    )

    # -------------------------------------------------------------------------
    # Roles de tenant nuevos (sistema): AI_ENGINEER, DATA_ENGINEER, DEVELOPER,
    # ANALYST, BILLING (continúa 50000000-...-004).
    # -------------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO roles (id, organization_id, name, description, is_system) VALUES
            ('50000000-0000-0000-0000-000000000005', NULL, 'ai_engineer',
             'Diseña agentes: prompts, knowledge, evaluación y deployments', true),
            ('50000000-0000-0000-0000-000000000006', NULL, 'data_engineer',
             'Conecta y sincroniza fuentes de datos', true),
            ('50000000-0000-0000-0000-000000000007', NULL, 'developer',
             'Desarrolla integraciones, API keys y agentes', true),
            ('50000000-0000-0000-0000-000000000008', NULL, 'analyst',
             'Consulta datos y analítica en modo lectura', true),
            ('50000000-0000-0000-0000-000000000009', NULL, 'billing',
             'Gestiona suscripción, facturación y uso', true)
        ON CONFLICT DO NOTHING
        """
    )
    _TENANT_ROLE_PERMS = {
        "ai_engineer": (
            "agents:read", "agents:write", "agents:version", "agents:execute",
            "kbs:read", "kbs:write", "sources:read", "sources:write",
            "rag:read", "rag:write", "prompt:read", "prompt:write",
            "usage:read", "deployments:read", "deployments:write",
        ),
        "data_engineer": (
            "sources:read", "sources:write", "connectors:read", "connectors:write",
            "kbs:read", "kbs:write", "rag:write", "rag:ingest", "usage:read",
        ),
        "developer": (
            "agents:read", "agents:write", "agents:version", "agents:execute",
            "projects:read", "projects:write", "apikeys:read", "apikeys:write",
            "rag:read", "prompt:read", "prompt:write",
            "deployments:read", "deployments:write",
        ),
        "analyst": (
            "agents:read", "kbs:read", "sources:read", "connectors:read",
            "rag:read", "usage:read", "deployments:read", "audit:read",
        ),
        "billing": ("billing:read", "billing:write", "usage:read"),
    }
    for role_name, codes in _TENANT_ROLE_PERMS.items():
        placeholders = ", ".join(f"'{c}'" for c in codes)
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id FROM roles r JOIN permissions p
            ON p.code IN ({placeholders})
            WHERE r.organization_id IS NULL AND r.name = '{role_name}'
            ON CONFLICT DO NOTHING
            """
        )

    # Los roles de invitación pasan a validarse contra BD: se elimina el CHECK.
    op.execute(
        "ALTER TABLE organization_invites DROP CONSTRAINT IF EXISTS "
        "organization_invites_role_check"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE organization_invites ADD CONSTRAINT "
        "organization_invites_role_check CHECK "
        "(role IN ('owner', 'admin', 'member', 'viewer'))"
    )
    op.execute(
        "DELETE FROM role_permissions WHERE role_id IN ("
        "  SELECT id FROM roles WHERE organization_id IS NULL AND name IN ("
        "  'ai_engineer', 'data_engineer', 'developer', 'analyst', 'billing')"
        ")"
    )
    op.execute(
        "DELETE FROM roles WHERE organization_id IS NULL AND name IN ("
        "  'ai_engineer', 'data_engineer', 'developer', 'analyst', 'billing')"
    )
    op.execute("DROP TABLE IF EXISTS user_platform_roles")
    op.execute("DROP TABLE IF EXISTS platform_role_permissions")
    op.execute("DROP TABLE IF EXISTS platform_roles")
    op.execute(
        "DELETE FROM permissions WHERE code IN ("
        "  'tenant.read', 'tenant.write', 'tenant.suspend', 'billing.read', "
        "  'billing.manage', 'models.read', 'models.manage', 'operations.read', "
        "  'operations.write', 'support.impersonate', 'audit.read', "
        "  'platform.settings.manage', 'platform.users.manage', 'analytics.read')"
    )

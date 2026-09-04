"""Workspaces — Tenant → Workspace → {Agents, Knowledge Bases, Connectors}.

Revision ID: 024
Revises: 023
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            slug VARCHAR(64) NOT NULL,
            description TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived')),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, slug)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspaces_org ON workspaces(organization_id)"
    )

    # workspace_id en agents, knowledge_bases y connectors (nullable, compat).
    for table in ("agents", "knowledge_bases", "connectors"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS workspace_id UUID "
            "REFERENCES workspaces(id) ON DELETE SET NULL"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_workspace "
            f"ON {table}(organization_id, workspace_id)"
        )

    # Ciclo de vida del agente: draft → configured → evaluating → ready →
    # deployed → archived (reemplaza el CHECK 'active'|'archived' de 021).
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check"
    )
    # Backfill ANTES de re-crear el CHECK: activos → ready, inactivos → archived.
    op.execute(
        "UPDATE agents SET status = CASE WHEN is_active THEN 'ready' ELSE 'archived' END "
        "WHERE status IN ('active', 'archived')"
    )
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_status_check "
        "CHECK (status IN ('draft', 'configured', 'evaluating', 'ready', "
        "'deployed', 'archived'))"
    )
    op.execute("ALTER TABLE agents ALTER COLUMN status SET DEFAULT 'draft'")

    # Permisos del catálogo (continúa 40000000-...-045).
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000046', 'workspaces:read',
             'Ver workspaces de la organización'),
            ('40000000-0000-0000-0000-000000000047', 'workspaces:write',
             'Crear/editar/archivar workspaces')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name IN ('owner', 'admin', 'member')
          AND p.code IN ('workspaces:read', 'workspaces:write')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_status_check"
    )
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT agents_status_check "
        "CHECK (status IN ('active', 'archived'))"
    )
    for table in ("connectors", "knowledge_bases", "agents"):
        op.execute(f"DROP INDEX IF EXISTS idx_{table}_workspace")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id")
    op.execute("DROP TABLE IF EXISTS workspaces")
    op.execute(
        "DELETE FROM permissions WHERE code IN ('workspaces:read', 'workspaces:write')"
    )

"""Environments + Deployments — ciclo de vida enterprise de agentes.

Revision ID: 022
Revises: 021
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS environments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(20) NOT NULL
                CHECK (name IN ('development', 'staging', 'production')),
            slug VARCHAR(30) NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deployments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            environment_id UUID NOT NULL REFERENCES environments(id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            agent_version_id UUID NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
            slug VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN (
                    'pending', 'deploying', 'healthy', 'degraded', 'failed', 'rolled_back'
                )),
            endpoint VARCHAR(500),
            deployed_by UUID,
            deployed_at TIMESTAMPTZ,
            rollback_from_id UUID REFERENCES deployments(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, slug)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployments_org_env "
        "ON deployments(organization_id, environment_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployments_agent "
        "ON deployments(organization_id, agent_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployments_version "
        "ON deployments(agent_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_env_org ON environments(organization_id)"
    )

    # Permisos del catalogo RBAC (continuacion de 40000000-...-028).
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000029', 'agents:version',
             'Crear y promover versiones de agentes'),
            ('40000000-0000-0000-0000-000000000030', 'deployments:read',
             'Ver deployments y entornos'),
            ('40000000-0000-0000-0000-000000000031', 'deployments:write',
             'Crear deployments, desplegar y hacer rollback')
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
          AND p.code IN ('agents:version', 'deployments:read', 'deployments:write')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'member'
          AND p.code IN ('agents:version', 'deployments:read')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deployments")
    op.execute("DROP TABLE IF EXISTS environments")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN ("
        "  SELECT id FROM permissions WHERE code IN "
        "  ('agents:version', 'deployments:read', 'deployments:write')"
        ")"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('agents:version', 'deployments:read', 'deployments:write')"
    )

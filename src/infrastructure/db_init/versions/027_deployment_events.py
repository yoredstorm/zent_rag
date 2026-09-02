"""Deployments Go Live — deployment_events + permisos granulares de deploy.

Revision ID: 027
Revises: 026
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS deployment_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            deployment_id UUID NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
            event VARCHAR(30) NOT NULL,
            actor_user_id UUID,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployment_events_deployment "
        "ON deployment_events(deployment_id, created_at ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_deployment_events_org "
        "ON deployment_events(organization_id, created_at DESC)"
    )

    # Permisos granulares de deploy (continúa 40000000-...-047).
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000048', 'deployments:deploy',
             'Crear deployments (desplegar versiones en entornos)'),
            ('40000000-0000-0000-0000-000000000049', 'deployments:rollback',
             'Ejecutar rollback de deployments'),
            ('40000000-0000-0000-0000-000000000050', 'deployments:promote',
             'Promover versiones a production')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name IN ('owner', 'admin')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deployment_events")
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN ("
        "  SELECT id FROM permissions WHERE code IN ("
        "  'deployments:deploy', 'deployments:rollback', 'deployments:promote')"
        ")"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ("
        "  'deployments:deploy', 'deployments:rollback', 'deployments:promote')"
    )

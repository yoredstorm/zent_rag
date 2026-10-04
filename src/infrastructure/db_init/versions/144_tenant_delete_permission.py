"""Permiso de plataforma tenant.delete (eliminación total de un tenant).

Revision ID: 144
Revises: 143

El hard delete de una organización (Control Center) exige un permiso propio:
`tenant.suspend` no debe habilitarlo, y solo super_admin / platform_admin lo
reciben. Aditiva e idempotente (ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "144"
down_revision: Union[str, None] = "143"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, description)
        VALUES (
            '40000000-0000-0000-0000-000000000110',
            'tenant.delete',
            'Eliminar tenants y toda su data (hard delete irreversible)'
        )
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO platform_role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM platform_roles r
        CROSS JOIN permissions p
        WHERE r.name IN ('super_admin', 'platform_admin')
          AND p.code = 'tenant.delete'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM platform_role_permissions
        WHERE permission_id IN (
            SELECT id FROM permissions WHERE code = 'tenant.delete'
        )
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'tenant.delete'")

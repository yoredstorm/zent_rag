"""Developer API scopes — rag:read, rag:write, agents:execute.

Revision ID: 012
Revises: 011
Create Date: 2026-08-23
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000023', 'rag:read',
             'Leer / consultar RAG (chat)'),
            ('40000000-0000-0000-0000-000000000024', 'rag:write',
             'Escribir en RAG (ingestion, fuentes, KBs)'),
            ('40000000-0000-0000-0000-000000000025', 'agents:execute',
             'Ejecutar agentes')
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
          AND p.code IN ('rag:read', 'rag:write', 'agents:execute')
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r CROSS JOIN permissions p
        WHERE r.organization_id IS NULL AND r.name = 'viewer'
          AND p.code IN ('rag:read')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (
            '40000000-0000-0000-0000-000000000023',
            '40000000-0000-0000-0000-000000000024',
            '40000000-0000-0000-0000-000000000025'
        )
        """
    )
    op.execute(
        """
        DELETE FROM permissions WHERE code IN
            ('rag:read', 'rag:write', 'agents:execute')
        """
    )

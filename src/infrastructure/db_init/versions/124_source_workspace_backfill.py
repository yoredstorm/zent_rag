"""Assign workspace to kb_sources left without one by the upload endpoints.

Revision ID: 124
Revises: 123
"""
from __future__ import annotations

from alembic import op

revision: str = "124"
down_revision: str = "123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Las subidas de archivos creaban fuentes con workspace_id NULL y la lista
    # (GET /sources) filtra por workspace activo: quedaban invisibles.
    # 1) Al workspace default de la organización.
    op.execute(
        """
        UPDATE kb_sources ks
        SET workspace_id = w.id
        FROM workspaces w
        WHERE ks.workspace_id IS NULL
          AND w.organization_id = ks.organization_id
          AND w.slug = 'default'
        """
    )
    # 2) Organizaciones sin workspace "default": si tienen uno solo, es ese.
    op.execute(
        """
        UPDATE kb_sources ks
        SET workspace_id = w.id
        FROM workspaces w
        WHERE ks.workspace_id IS NULL
          AND w.organization_id = ks.organization_id
          AND (
              SELECT count(*) FROM workspaces w2
              WHERE w2.organization_id = ks.organization_id
          ) = 1
        """
    )


def downgrade() -> None:
    # Irreversible: no se puede distinguir qué filas eran NULL antes.
    pass

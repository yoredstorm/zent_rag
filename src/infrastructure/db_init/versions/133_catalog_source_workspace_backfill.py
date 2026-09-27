"""Assign workspace to catalog_sources left without one.

La migración 085 agregó `catalog_sources.workspace_id` pero nunca backfilleó
las filas existentes (085 es DDL puro). Los endpoints que listan fuentes
(`/catalog/sources`, `/knowledge/learning/sources`) filtran por workspace
activo, así que las fuentes con workspace_id NULL quedaban invisibles:
la pantalla de Actividad no mostraba nada que aprender.

Mismo criterio que la 124 (kb_sources):
1) workspace default de la organización;
2) organizaciones con un solo workspace.

Revision ID: 133
Revises: 132
"""
from __future__ import annotations

from alembic import op

revision: str = "133"
down_revision: str = "132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE catalog_sources cs
        SET workspace_id = w.id
        FROM workspaces w
        WHERE cs.workspace_id IS NULL
          AND w.organization_id = cs.organization_id
          AND w.slug = 'default'
        """
    )
    op.execute(
        """
        UPDATE catalog_sources cs
        SET workspace_id = w.id
        FROM workspaces w
        WHERE cs.workspace_id IS NULL
          AND w.organization_id = cs.organization_id
          AND (
              SELECT count(*) FROM workspaces w2
              WHERE w2.organization_id = cs.organization_id
          ) = 1
        """
    )


def downgrade() -> None:
    # Irreversible: no se puede distinguir qué filas eran NULL antes.
    pass

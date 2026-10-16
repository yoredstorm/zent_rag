"""Workflow packages - zent.workflow.package/v1 en workflows y templates.

Revision ID: 156
Revises: 155

Aditiva.
- workflows.package: metadata del paquete importado (schema, versions,
  requirements, checksum). Vacio para workflows nativos.
- workflow_templates.package + graph: un solo sistema de plantillas.
  `steps` legacy se conserva para compatibilidad; `graph`/`package` son el
  formato nuevo.
"""
from __future__ import annotations

from alembic import op

revision: str = "156"
down_revision: str = "155"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflows ADD COLUMN IF NOT EXISTS package JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS package JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS graph JSONB"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_templates DROP COLUMN IF EXISTS graph")
    op.execute("ALTER TABLE workflow_templates DROP COLUMN IF EXISTS package")
    op.execute("ALTER TABLE workflows DROP COLUMN IF EXISTS package")

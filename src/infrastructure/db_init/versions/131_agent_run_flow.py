"""Agent flow canónico — el run de agente guarda su Flow v2.

El flow deja de reconstruirse en el portal: el backend es la fuente de verdad y
lo persiste con el run. `steps` sigue intacto (raw runtime steps) para
diagnóstico y para portales viejos.

Revision ID: 131
Revises: 130
"""
from __future__ import annotations

from alembic import op

revision: str = "131"
down_revision: str = "130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_runs
            ADD COLUMN IF NOT EXISTS flow JSONB
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE agent_runs
            DROP COLUMN IF EXISTS flow
        """
    )

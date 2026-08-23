"""Connector Platform — libera el CHECK de tipos de conectores.

Revision ID: 008
Revises: 007
Create Date: 2026-08-21

La Connector Platform registra tipos dinámicamente vía plugins; el CHECK
estático ('sql','api','files') bloqueaba tipos nuevos. Se elimina.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE connectors DROP CONSTRAINT IF EXISTS connectors_type_check"
    )
    op.execute(
        "ALTER TABLE connectors ALTER COLUMN type TYPE VARCHAR(30)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE connectors ADD CONSTRAINT connectors_type_check "
        "CHECK (type IN ('sql','api','files'))"
    )

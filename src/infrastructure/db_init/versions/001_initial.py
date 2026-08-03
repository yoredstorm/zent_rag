"""Initial baseline — marca el esquema actual como base

Revision ID: 001
Revises: None
Create Date: 2026-07-31 00:00:00.000000

Esta migracion no crea tablas. El esquema existente (creado por los scripts SQL
en db_init/) se trata como linea base. Las migraciones futuras construiran
sobre esta revision con ALTER, CREATE INDEX, etc.
"""
from __future__ import annotations

from typing import Sequence, Union

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

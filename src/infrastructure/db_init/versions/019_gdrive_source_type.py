"""Google Drive source type (plugin-registered; 008 pattern).

Revision ID: 019
Revises: 018
Create Date: 2026-08-29

kb_sources.type no lleva CHECK (004/008): los tipos viven en el registry.
Esta revisión documenta `gdrive` y elimina un CHECK residual si existiera.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE kb_sources DROP CONSTRAINT IF EXISTS kb_sources_type_check"
    )
    op.execute("ALTER TABLE kb_sources ALTER COLUMN type TYPE VARCHAR(40)")


def downgrade() -> None:
    # Tipos siguen siendo plugin-registered; no se reintroduce CHECK.
    return

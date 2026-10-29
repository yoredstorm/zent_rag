"""Evidence ledger paging index.

Revision ID: 175
Revises: 174

Additive only. El índice reproduce el orden observable del Explorador
(`strength DESC NULLS LAST, created_at DESC, id ASC`) para que la lectura
paginada de 10.000+ evidencias no dependa de un sort completo en memoria.
No cambia datos ni el contrato del cursor.
"""
from __future__ import annotations

from alembic import op

revision: str = "175"
down_revision: str = "174"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_evidence_ledger_paging
        ON evidence_ledger (
            organization_id,
            source_id,
            strength DESC NULLS LAST,
            created_at DESC,
            id ASC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_evidence_ledger_paging")

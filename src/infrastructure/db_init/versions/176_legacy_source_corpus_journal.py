"""Legacy source corpus backfill journal.

Revision ID: 176
Revises: 175

Additive only. Registra el antes/después de cada asignación de corpus para
fuentes históricas. No modifica kb_sources por sí misma; el CLI
`legacy_source_corpus_backfill` exige plan, checksum y aprobación.
"""
from __future__ import annotations

from alembic import op

revision: str = "176"
down_revision: str = "175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS legacy_source_corpus_journal (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            plan_id UUID NOT NULL,
            plan_sha256 VARCHAR(64) NOT NULL,
            organization_id UUID NOT NULL,
            workspace_id UUID,
            source_id UUID NOT NULL,
            knowledge_base_id UUID,
            before_corpus_id UUID,
            after_corpus_id UUID NOT NULL,
            before_updated_at TIMESTAMPTZ,
            after_updated_at TIMESTAMPTZ NOT NULL,
            actor VARCHAR(120) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'applied',
            conflict_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            rolled_back_at TIMESTAMPTZ,
            UNIQUE (plan_id, source_id)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_legacy_source_corpus_journal_org_source
        ON legacy_source_corpus_journal (organization_id, source_id)
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS idx_legacy_source_corpus_journal_org_source"
    )
    op.execute("DROP TABLE IF EXISTS legacy_source_corpus_journal")

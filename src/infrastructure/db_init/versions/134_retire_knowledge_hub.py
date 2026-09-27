"""Retiro del Knowledge Hub legacy.

El Knowledge Hub quedó retirado (página portal, API, scheduler y dashboard
admin). Sus tablas se archivan con prefijo ``legacy_`` y los gaps reales que
acumuló ``knowledge_gaps`` (escritos solo por Copilot) se migran a
``context_gaps`` con gap_type ``UNRESOLVED_QUERY``, la superficie canónica que
ya consumen IntelligenceEngine, ``/evaluation/impact`` y Governance.

``documents`` no se toca aquí: la tabla conserva lectores (DR Center, export
de datos, workflows legacy, purge de demo) y, sin writers, sus filas quedan
como histórico. Su retiro físico va en una migración posterior.

Revision ID: 134
Revises: 133
"""
from __future__ import annotations

from alembic import op

revision: str = "134"
down_revision: str = "133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Gaps reales del Hub → context_gaps canónico (idempotente por upsert).
    op.execute(
        """
        INSERT INTO context_gaps (
            organization_id, gap_type, concept, title, description,
            evidence_hints, question, occurrences, status,
            first_seen_at, last_seen_at
        )
        SELECT organization_id,
               'UNRESOLVED_QUERY',
               concept,
               concept,
               NULL,
               '[]'::jsonb,
               MAX(question),
               SUM(occurrences)::int,
               CASE WHEN bool_or(status = 'open') THEN 'open' ELSE 'resolved' END,
               MIN(first_seen),
               MAX(last_seen_at)
        FROM (
            SELECT organization_id,
                   LEFT(query, 160) AS concept,
                   query AS question,
                   occurrences,
                   status,
                   created_at AS first_seen,
                   last_seen_at
            FROM knowledge_gaps
        ) migrated
        GROUP BY organization_id, concept
        ON CONFLICT (organization_id, gap_type, concept) DO UPDATE SET
            occurrences = context_gaps.occurrences + EXCLUDED.occurrences,
            last_seen_at = GREATEST(context_gaps.last_seen_at, EXCLUDED.last_seen_at),
            status = CASE
                WHEN context_gaps.status = 'open' OR EXCLUDED.status = 'open' THEN 'open'
                ELSE context_gaps.status
            END
        """
    )

    # 2. Archivar tablas del Hub (sin readers tras el retiro).
    op.execute(
        "ALTER INDEX IF EXISTS idx_knowledge_refreshes_source "
        "RENAME TO idx_legacy_knowledge_refreshes_source"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_knowledge_gaps_org RENAME TO idx_legacy_knowledge_gaps_org"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_knowledge_sources_org "
        "RENAME TO idx_legacy_knowledge_sources_org"
    )
    op.execute("ALTER TABLE IF EXISTS knowledge_refreshes RENAME TO legacy_knowledge_refreshes")
    op.execute("ALTER TABLE IF EXISTS knowledge_gaps RENAME TO legacy_knowledge_gaps")
    op.execute("ALTER TABLE IF EXISTS knowledge_sources RENAME TO legacy_knowledge_sources")


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS legacy_knowledge_sources RENAME TO knowledge_sources")
    op.execute("ALTER TABLE IF EXISTS legacy_knowledge_gaps RENAME TO knowledge_gaps")
    op.execute("ALTER TABLE IF EXISTS legacy_knowledge_refreshes RENAME TO knowledge_refreshes")
    op.execute(
        "ALTER INDEX IF EXISTS idx_legacy_knowledge_sources_org "
        "RENAME TO idx_knowledge_sources_org"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_legacy_knowledge_gaps_org RENAME TO idx_knowledge_gaps_org"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_legacy_knowledge_refreshes_source "
        "RENAME TO idx_knowledge_refreshes_source"
    )
    # Los gaps migrados no se borran de context_gaps: pueden convivir con filas
    # escritas por IntelligenceEngine con el mismo gap_type. Pérdida aceptada.

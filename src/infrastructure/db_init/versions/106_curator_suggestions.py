"""Knowledge Curator — sugerencias gobernadas (Phase 7).

knowledge_curator_suggestions guarda propuestas INFERRED/OBSERVED generadas
desde runs cognitivos (conflictos, debates, cobertura). Nacen PROPOSED; solo
una decisión humana explícita las pasa a APPROVED/REJECTED.

Revision ID: 106
Revises: 105
"""
from __future__ import annotations

from alembic import op

revision: str = "106"
down_revision: str = "105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_curator_suggestions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            run_id UUID REFERENCES cognitive_runs(id) ON DELETE SET NULL,
            kind VARCHAR(32) NOT NULL
                CHECK (kind IN ('glossary_term','synonym','business_rule','relationship','concept_review','fact_candidate')),
            status VARCHAR(16) NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed','approved','rejected')),
            title TEXT NOT NULL,
            reasoning TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            claim_ids UUID[] NOT NULL DEFAULT '{}'::uuid[],
            provenance VARCHAR(16) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence >= 0 AND confidence <= 1),
            created_by UUID,
            decided_by UUID,
            decided_at TIMESTAMPTZ,
            decision_reason TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_curator_approval_law
                CHECK (status <> 'approved' OR decided_by IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_curator_suggestions_org_status "
        "ON knowledge_curator_suggestions(organization_id, status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_curator_suggestions_org_run "
        "ON knowledge_curator_suggestions(organization_id, run_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_curator_suggestions")

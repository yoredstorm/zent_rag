"""Phase 33D — AI Business Questions & Human Validation.

Crea knowledge_questions (preguntas de negocio originadas en evidencia real)
y knowledge_feedback (respuestas humanas convertidas en conocimiento
reutilizable). Aislamiento estricto por organization_id.

Revision ID: 097
Revises: 096
"""
from __future__ import annotations

from alembic import op

revision: str = "097"
down_revision: str = "096"
branch_labels = None
depends_on = None

_QUESTION_TYPES = (
    "('enum_meaning','field_ambiguity','table_variant','tax_inclusion',"
    "'relationship_meaning','business_rule','metric_definition','llm_question','other')"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_questions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID,
            run_id UUID REFERENCES knowledge_learning_runs(id) ON DELETE SET NULL,
            catalog_table_id UUID REFERENCES catalog_tables(id) ON DELETE CASCADE,
            entity_id UUID,
            field_id UUID,
            column_id UUID,
            relationship_id UUID,
            question_key VARCHAR(200) NOT NULL,
            question_type VARCHAR(30) NOT NULL
                CHECK (question_type IN {_QUESTION_TYPES}),
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            options JSONB NOT NULL DEFAULT '[]'::jsonb,
            answer_schema JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            priority VARCHAR(10) NOT NULL DEFAULT 'medium'
                CHECK (priority IN ('critical','high','medium','low')),
            priority_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            impact JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            status VARCHAR(12) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','answered','skipped','deferred','expired')),
            answer JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            structured_answer JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            answered_by UUID,
            answered_at TIMESTAMPTZ,
            confidence_before DOUBLE PRECISION,
            confidence_after DOUBLE PRECISION,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, question_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_questions_org_status_priority "
        "ON knowledge_questions(organization_id, status, priority)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_questions_org_run "
        "ON knowledge_questions(organization_id, run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_questions_org_source "
        "ON knowledge_questions(organization_id, source_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_feedback (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            question_id UUID REFERENCES knowledge_questions(id) ON DELETE SET NULL,
            run_id UUID,
            source_id UUID,
            knowledge_type VARCHAR(40) NOT NULL DEFAULT 'question',
            knowledge_id VARCHAR(80),
            question TEXT NOT NULL DEFAULT '',
            answer TEXT NOT NULL DEFAULT '',
            structured_answer JSONB NOT NULL DEFAULT '{}'::jsonb,
            source VARCHAR(40) NOT NULL DEFAULT 'question'
                CHECK (source IN ('question','review_queue','studio','import')),
            applied BOOLEAN NOT NULL DEFAULT false,
            applied_to JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_feedback_org_created "
        "ON knowledge_feedback(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_feedback_org_question "
        "ON knowledge_feedback(organization_id, question_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_feedback")
    op.execute("DROP TABLE IF EXISTS knowledge_questions")

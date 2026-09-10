"""Phase 33B — LLM Semantic Intelligence: análisis por tabla y cache durable.

Crea knowledge_llm_analyses (1 análisis por organization + tabla + fingerprint
+ prompt_version + modelo) y habilita sugerencias de tipo business_rule.

Nunca se almacena chain-of-thought: solo evidence y reasoning_summary corta,
apta para el usuario. El contexto enviado al LLM se registra por digest y
metadata (nunca secretos ni PII).

Revision ID: 095
Revises: 094
"""
from __future__ import annotations

from alembic import op

revision: str = "095"
down_revision: str = "094"
branch_labels = None
depends_on = None

_SUGGESTION_TYPES = (
    "('entity_identification','table_identification',"
    "'relationship_candidate','enum_definition','field_mapping',"
    "'metric_proposal','glossary_term','document_fact','business_rule')"
)

_SUGGESTION_TYPES_PREVIOUS = (
    "('entity_identification','table_identification',"
    "'relationship_candidate','enum_definition','field_mapping',"
    "'metric_proposal','glossary_term','document_fact')"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_llm_analyses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID,
            run_id UUID REFERENCES knowledge_learning_runs(id) ON DELETE SET NULL,
            table_id UUID REFERENCES catalog_tables(id) ON DELETE CASCADE,
            schema_fingerprint VARCHAR(64) NOT NULL,
            prompt_version VARCHAR(20) NOT NULL DEFAULT 'kl-v1',
            model VARCHAR(120) NOT NULL DEFAULT '',
            status VARCHAR(12) NOT NULL DEFAULT 'completed'
                CHECK (status IN ('completed','failed','skipped')),
            context_digest VARCHAR(64) NOT NULL DEFAULT '',
            context_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
            result JSONB NOT NULL DEFAULT '{}'::jsonb,
            reasoning_summary TEXT,
            confidence DOUBLE PRECISION,
            tokens_input INT NOT NULL DEFAULT 0,
            tokens_output INT NOT NULL DEFAULT 0,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            estimated_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, table_id, schema_fingerprint, prompt_version, model)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_run "
        "ON knowledge_llm_analyses(organization_id, run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_source "
        "ON knowledge_llm_analyses(organization_id, source_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_llm_analyses_org_table "
        "ON knowledge_llm_analyses(organization_id, table_id, created_at DESC)"
    )

    # Sugerencias de reglas de negocio (hallazgos del LLM, siempre revisables).
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "DROP CONSTRAINT IF EXISTS catalog_suggestions_type_check"
    )
    op.execute(
        "ALTER TABLE catalog_suggestions "
        f"ADD CONSTRAINT catalog_suggestions_type_check CHECK (type IN {_SUGGESTION_TYPES})"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_llm_analyses")
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "DROP CONSTRAINT IF EXISTS catalog_suggestions_type_check"
    )
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "ADD CONSTRAINT catalog_suggestions_type_check CHECK "
        f"(type IN {_SUGGESTION_TYPES_PREVIOUS})"
    )

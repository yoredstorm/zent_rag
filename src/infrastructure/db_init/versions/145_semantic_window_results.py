"""Progressive Semantic Ingestion — resultados por ventana + estado semántico.

Dos tablas de la Fase 3:

1. ``knowledge_semantic_window_results``: resultado estructurado de la
   comprensión local de cada ventana (items con provenance, fingerprint de
   contenido, carry fingerprint del estado seleccionado, status, calidad,
   tokens LLM). Es el checkpoint por ventana: fingerprint igual = SKIP.
2. ``knowledge_semantic_states``: estado compacto por ventana (glosario,
   símbolos, reglas, referencias sin resolver, continuaciones abiertas,
   topics, temporal, aliases, relaciones pendientes, conflictos) con
   fingerprint. Permite reanudar desde la ventana N.

Aditiva: no toca tablas existentes.

Revision ID: 145
Revises: 144
"""
from __future__ import annotations

from alembic import op

revision: str = "145"
down_revision: str = "144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_window_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            window_index INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'complete',
            fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            carry_fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION,
            quality JSONB NOT NULL DEFAULT '{}',
            items JSONB NOT NULL DEFAULT '[]',
            item_counts JSONB NOT NULL DEFAULT '{}',
            tokens_used INTEGER NOT NULL DEFAULT 0,
            llm_calls INTEGER NOT NULL DEFAULT 0,
            error VARCHAR(1000),
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, window_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_window_results_org_doc_status "
        "ON knowledge_semantic_window_results(organization_id, document_id, status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_states (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            window_index INTEGER NOT NULL,
            fingerprint VARCHAR(64) NOT NULL DEFAULT '',
            state JSONB NOT NULL DEFAULT '{}',
            stats JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, window_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_semantic_states_org_doc "
        "ON knowledge_semantic_states(organization_id, document_id, window_index)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_states")
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_window_results")

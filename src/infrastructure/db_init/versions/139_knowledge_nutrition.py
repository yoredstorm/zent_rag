"""Knowledge Nutrition — probes, evaluaciones, estado y acciones.

Cuatro tablas acotadas (no una por concepto):

1. ``knowledge_retrieval_probes``: preguntas de acceptance versionadas y
   re-ejecutables sin re-ingerir la fuente. Guardan la evidencia esperada.
2. ``knowledge_retrieval_evaluations``: snapshot de cada corrida (métricas +
   probes fallidos) para tendencia y auditoría.
3. ``knowledge_nutrition_state``: dimensiones del nutrition score por scope
   (document/source/knowledge_area/workspace) + perfil de demanda. JSONB: el
   score evoluciona sin migrar columnas.
4. ``knowledge_nutrition_actions``: acciones append-only con evidencia,
   confianza, política y versión. ``destructive`` es siempre false en esta capa.

Revision ID: 139
Revises: 138
"""
from __future__ import annotations

from alembic import op

revision: str = "139"
down_revision: str = "138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_retrieval_probes (
            probe_id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            semantic_unit_id VARCHAR(120),
            query TEXT NOT NULL,
            query_type VARCHAR(40) NOT NULL,
            expected_document_id VARCHAR(80) NOT NULL DEFAULT '',
            expected_section_id VARCHAR(80),
            expected_unit_id VARCHAR(120),
            expected_entity_ids JSONB NOT NULL DEFAULT '[]',
            generated_by VARCHAR(80) NOT NULL DEFAULT 'semantic_enrichment',
            generator_version VARCHAR(40) NOT NULL DEFAULT '',
            policy_version VARCHAR(40) NOT NULL DEFAULT '',
            active BOOLEAN NOT NULL DEFAULT true,
            last_result JSONB,
            last_evaluated_at TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_probes_org_document "
        "ON knowledge_retrieval_probes(organization_id, document_id, active)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_probes_org_type "
        "ON knowledge_retrieval_probes(organization_id, query_type)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_retrieval_evaluations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            mode VARCHAR(20) NOT NULL DEFAULT 'warn',
            accepted BOOLEAN NOT NULL DEFAULT false,
            retrievable BOOLEAN NOT NULL DEFAULT false,
            probes_total INTEGER NOT NULL DEFAULT 0,
            probes_passed INTEGER NOT NULL DEFAULT 0,
            probes_failed INTEGER NOT NULL DEFAULT 0,
            recall_at_1 DOUBLE PRECISION,
            recall_at_3 DOUBLE PRECISION,
            recall_at_5 DOUBLE PRECISION,
            mrr DOUBLE PRECISION,
            metrics JSONB NOT NULL DEFAULT '{}',
            failed_probes JSONB NOT NULL DEFAULT '[]',
            generator_version VARCHAR(40) NOT NULL DEFAULT '',
            policy_version VARCHAR(40) NOT NULL DEFAULT '',
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_evaluations_org_document "
        "ON knowledge_retrieval_evaluations(organization_id, document_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_nutrition_state (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            scope VARCHAR(30) NOT NULL DEFAULT 'document',
            scope_id VARCHAR(120) NOT NULL,
            dimensions JSONB NOT NULL DEFAULT '{}',
            nutrition_score DOUBLE PRECISION,
            formula_version VARCHAR(40) NOT NULL DEFAULT '',
            measured_dimensions INTEGER NOT NULL DEFAULT 0,
            total_dimensions INTEGER NOT NULL DEFAULT 0,
            coverage DOUBLE PRECISION,
            demand_profile JSONB NOT NULL DEFAULT '{}',
            details JSONB NOT NULL DEFAULT '{}',
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, scope, scope_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_nutrition_state_org "
        "ON knowledge_nutrition_state(organization_id, scope, updated_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_nutrition_actions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID,
            failure_type VARCHAR(60) NOT NULL,
            action_type VARCHAR(60) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('observed','proposed','applied','rejected')),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            reason VARCHAR(1000) NOT NULL DEFAULT '',
            query TEXT,
            evidence JSONB NOT NULL DEFAULT '{}',
            policy_version VARCHAR(40) NOT NULL DEFAULT '',
            model_version VARCHAR(80),
            destructive BOOLEAN NOT NULL DEFAULT false,
            requires_review BOOLEAN NOT NULL DEFAULT true,
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_nutrition_actions_org "
        "ON knowledge_nutrition_actions(organization_id, status, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_nutrition_actions_document "
        "ON knowledge_nutrition_actions(organization_id, document_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_nutrition_actions")
    op.execute("DROP TABLE IF EXISTS knowledge_nutrition_state")
    op.execute("DROP TABLE IF EXISTS knowledge_retrieval_evaluations")
    op.execute("DROP TABLE IF EXISTS knowledge_retrieval_probes")

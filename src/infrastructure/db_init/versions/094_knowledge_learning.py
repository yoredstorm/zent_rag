"""Phase 33A — Knowledge Learning Engine: runs, steps, eventos y score.

Crea la persistencia del pipeline explícito de aprendizaje (conexión →
discovery → profiling → semántica → relaciones → validación → indexado →
evaluación → readiness). Compatible con training_runs: un learning run puede
referenciar un training_run_id sin duplicar su semántica.

También agrega catalog_tables.schema_fingerprint para cachear análisis
semántico por fingerprint (FASE 33B) y los permisos knowledge:read/write.

Revision ID: 094
Revises: 093
"""
from __future__ import annotations

from alembic import op

revision: str = "094"
down_revision: str = "093"
branch_labels = None
depends_on = None

_STAGES = (
    "connecting", "discovering_schema", "profiling", "detecting_entities",
    "analyzing_fields", "detecting_relationships", "llm_reasoning",
    "generating_questions", "awaiting_validation", "chunking", "embedding",
    "indexing", "evaluating", "scoring", "ready",
)
_STAGES_SQL = "(" + ", ".join(f"'{s}'" for s in _STAGES) + ")"

_RUN_STATUS = "('queued','running','awaiting_validation','completed','failed','cancelled')"


def upgrade() -> None:
    # ------------------------------------------------------------------ runs
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_learning_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            catalog_source_id UUID REFERENCES catalog_sources(id) ON DELETE SET NULL,
            kb_source_id UUID,
            training_run_id UUID,
            trigger VARCHAR(20) NOT NULL DEFAULT 'manual'
                CHECK (trigger IN ('manual','scheduled','onboarding')),
            status VARCHAR(24) NOT NULL DEFAULT 'queued'
                CHECK (status IN {_RUN_STATUS}),
            current_stage VARCHAR(30) NOT NULL DEFAULT 'connecting'
                CHECK (current_stage IN {_STAGES_SQL}),
            overall_progress INT NOT NULL DEFAULT 0,
            stage_progress INT NOT NULL DEFAULT 0,
            gate VARCHAR(16),
            tables_analyzed INT NOT NULL DEFAULT 0,
            entities_detected INT NOT NULL DEFAULT 0,
            fields_detected INT NOT NULL DEFAULT 0,
            relationships_detected INT NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            error_summary JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_runs_org_created "
        "ON knowledge_learning_runs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_runs_org_source_status "
        "ON knowledge_learning_runs(organization_id, catalog_source_id, status)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_learning_active_run "
        "ON knowledge_learning_runs(organization_id, catalog_source_id) "
        "WHERE status IN ('queued','running','awaiting_validation')"
    )

    # ----------------------------------------------------------------- steps
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_learning_steps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            run_id UUID NOT NULL REFERENCES knowledge_learning_runs(id) ON DELETE CASCADE,
            stage VARCHAR(30) NOT NULL CHECK (stage IN {_STAGES_SQL}),
            sequence INT NOT NULL DEFAULT 0,
            status VARCHAR(12) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','completed','skipped','failed')),
            progress INT NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            error TEXT,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (run_id, stage)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_learning_steps_run "
        "ON knowledge_learning_steps(run_id, sequence)"
    )

    # ---------------------------------------------------------------- events
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            seq BIGSERIAL NOT NULL,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            run_id UUID REFERENCES knowledge_learning_runs(id) ON DELETE CASCADE,
            source_id UUID,
            event_type VARCHAR(60) NOT NULL,
            stage VARCHAR(30),
            category VARCHAR(20) NOT NULL DEFAULT 'system'
                CHECK (category IN ('discovery','ai','validation','indexing','system')),
            severity VARCHAR(10) NOT NULL DEFAULT 'info'
                CHECK (severity IN ('info','success','warning','error')),
            message TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_events_seq ON knowledge_events(seq)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_created "
        "ON knowledge_events(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_run_seq "
        "ON knowledge_events(organization_id, run_id, seq)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_events_org_category "
        "ON knowledge_events(organization_id, category, seq DESC)"
    )

    # ---------------------------------------------------------------- scores
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_scores (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            scope_key VARCHAR(80) NOT NULL DEFAULT 'organization',
            source_id UUID,
            run_id UUID REFERENCES knowledge_learning_runs(id) ON DELETE SET NULL,
            overall DOUBLE PRECISION NOT NULL DEFAULT 0,
            gate VARCHAR(16) NOT NULL DEFAULT 'NOT_READY'
                CHECK (gate IN ('NOT_READY','LEARNING','NEEDS_INPUT','READY','DEGRADED')),
            dimensions JSONB NOT NULL DEFAULT '[]'::jsonb,
            reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            weights JSONB NOT NULL DEFAULT '{}'::jsonb,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, scope_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_scores_org_source "
        "ON knowledge_scores(organization_id, source_id)"
    )

    # -------------------------------------------------------------- settings
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_learning_settings (
            organization_id UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            weights JSONB NOT NULL DEFAULT '{}'::jsonb,
            thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------- fingerprint de tablas
    op.execute(
        "ALTER TABLE catalog_tables "
        "ADD COLUMN IF NOT EXISTS schema_fingerprint VARCHAR(64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_tables_fingerprint "
        "ON catalog_tables(organization_id, schema_fingerprint)"
    )

    # ------------------------------------------------------------ permisos
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000053', 'knowledge:read',
             'Ver el aprendizaje de conocimiento, score y actividad'),
            ('40000000-0000-0000-0000-000000000054', 'knowledge:write',
             'Ejecutar aprendizaje y configurar readiness por tenant')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name IN ('owner','admin','member') "
        "AND p.code IN ('knowledge:read','knowledge:write') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'viewer' "
        "AND p.code = 'knowledge:read' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in (
        "knowledge_learning_settings",
        "knowledge_scores",
        "knowledge_events",
        "knowledge_learning_steps",
        "knowledge_learning_runs",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "DROP INDEX IF EXISTS idx_catalog_tables_fingerprint"
    )
    op.execute(
        "ALTER TABLE catalog_tables DROP COLUMN IF EXISTS schema_fingerprint"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('knowledge:read','knowledge:write')"
    )

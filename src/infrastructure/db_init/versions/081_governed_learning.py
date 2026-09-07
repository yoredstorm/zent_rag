"""PHASE 25 — Governed Learning: Context Advisor, Learning Loop, Spider, ECG.

Revision ID: 081
Revises: 080
"""
from __future__ import annotations

from alembic import op

revision: str = "081"
down_revision: str = "080"
branch_labels = None
depends_on = None

_GAP_TYPES = (
    "MISSING_SOURCE", "MISSING_TABLE", "MISSING_FIELD", "MISSING_RELATIONSHIP",
    "MISSING_BUSINESS_TERM", "MISSING_METRIC", "UNDEFINED_ENUM",
    "AMBIGUOUS_TERM", "STALE_SOURCE", "LOW_DATA_QUALITY", "SOURCE_CONFLICT",
    "PERMISSION_LIMITATION", "UNSUPPORTED_OPERATION",
)

_GAP_TYPES_SQL = "(" + ", ".join(f"'{t}'" for t in _GAP_TYPES) + ")"


def upgrade() -> None:
    # -------------------------------------------------------------- context_gaps
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_gap_type_check "
        f"CHECK (gap_type IN {_GAP_TYPES_SQL})"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS question TEXT"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS impact JSONB NOT NULL DEFAULT '{}'::jsonb"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS resolved_by UUID"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ"
    )

    # ------------------------------------------------------- intelligence_traces
    op.execute(
        "ALTER TABLE intelligence_traces ADD COLUMN IF NOT EXISTS user_id UUID"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_intelligence_traces_org_user "
        "ON intelligence_traces(organization_id, user_id)"
    )

    # ----------------------------------------------------------- catalog_lineage
    op.execute(
        "ALTER TABLE catalog_lineage DROP CONSTRAINT IF EXISTS catalog_lineage_relation_check"
    )
    op.execute(
        "ALTER TABLE catalog_lineage ADD CONSTRAINT catalog_lineage_relation_check "
        "CHECK (relation IN ('DEFINES','USES','DEPENDS_ON','MAPS_TO',"
        "'IS_AUTHORITY_FOR','SOURCE_OF','AGENT_USES','QUESTION_REFERENCES',"
        "'GAP_AFFECTS','EVALUATION_TESTS','DOCUMENT_DEFINES'))"
    )

    # ---------------------------------------------------------- catalog_enum_values
    op.execute(
        "ALTER TABLE catalog_enum_values ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1"
    )

    # ------------------------------------------------------------- improvements
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS improvement_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            priority VARCHAR(12) NOT NULL DEFAULT 'medium'
                CHECK (priority IN ('critical','high','medium','low')),
            gap_type VARCHAR(40) NOT NULL,
            title VARCHAR(400) NOT NULL,
            description TEXT,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            affected_queries INT NOT NULL DEFAULT 0,
            affected_users INT NOT NULL DEFAULT 0,
            affected_agents INT NOT NULL DEFAULT 0,
            affected_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            recommended_action TEXT,
            estimated_impact JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'OPEN'
                CHECK (status IN ('OPEN','IN_REVIEW','RESOLVED','DISMISSED','BLOCKED')),
            owner VARCHAR(120),
            suggested_concept VARCHAR(160),
            cluster_key VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            UNIQUE (organization_id, gap_type, cluster_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_improvement_items_org_status "
        "ON improvement_items(organization_id, status, priority)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            knowledge_type VARCHAR(30) NOT NULL,
            knowledge_id VARCHAR(64) NOT NULL,
            action VARCHAR(20) NOT NULL
                CHECK (action IN ('approve','reject','edit_approve')),
            acted_by UUID,
            reason TEXT,
            source_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            previous_version JSONB NOT NULL DEFAULT '{}'::jsonb,
            new_version JSONB NOT NULL DEFAULT '{}'::jsonb,
            replay_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_approval_records_org_knowledge "
        "ON approval_records(organization_id, knowledge_type, knowledge_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_replays (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            knowledge_type VARCHAR(30) NOT NULL,
            knowledge_id VARCHAR(64) NOT NULL,
            trigger VARCHAR(10) NOT NULL DEFAULT 'manual'
                CHECK (trigger IN ('auto','manual')),
            eval_run_id UUID,
            baseline_run_id UUID,
            before JSONB NOT NULL DEFAULT '{}'::jsonb,
            after JSONB NOT NULL DEFAULT '{}'::jsonb,
            verdict VARCHAR(10) NOT NULL DEFAULT 'unknown'
                CHECK (verdict IN ('pass','warn','fail','unknown')),
            status VARCHAR(12) NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','completed','failed')),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_learning_replays_org_knowledge "
        "ON learning_replays(organization_id, knowledge_type, knowledge_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_conflicts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            concept VARCHAR(160) NOT NULL,
            question TEXT,
            source_a VARCHAR(200) NOT NULL,
            value_a JSONB,
            source_b VARCHAR(200) NOT NULL,
            value_b JSONB,
            resolved_by_authority BOOLEAN NOT NULL DEFAULT false,
            authority_source VARCHAR(200),
            status VARCHAR(12) NOT NULL DEFAULT 'recorded'
                CHECK (status IN ('recorded','resolved')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_conflicts_org_created "
        "ON source_conflicts(organization_id, created_at DESC)"
    )

    # ------------------------------------------------------------ spider
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS spider_policies (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(150) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT true,
            schedule_hours INT NOT NULL DEFAULT 24,
            allowed_source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed_schemas JSONB NOT NULL DEFAULT '[]'::jsonb,
            excluded_objects JSONB NOT NULL DEFAULT '[]'::jsonb,
            profiling_level VARCHAR(12) NOT NULL DEFAULT 'standard'
                CHECK (profiling_level IN ('none','standard','deep')),
            max_cost INT NOT NULL DEFAULT 500,
            max_duration_min INT NOT NULL DEFAULT 60,
            sampling_policy VARCHAR(14) NOT NULL DEFAULT 'conservative'
                CHECK (sampling_policy IN ('none','conservative','standard')),
            pii_policy VARCHAR(8) NOT NULL DEFAULT 'never'
                CHECK (pii_policy IN ('never','mask')),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS spider_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            policy_id UUID NOT NULL REFERENCES spider_policies(id) ON DELETE CASCADE,
            status VARCHAR(12) NOT NULL DEFAULT 'running'
                CHECK (status IN ('running','completed','failed','cancelled')),
            findings JSONB NOT NULL DEFAULT '[]'::jsonb,
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_spider_runs_policy "
        "ON spider_runs(policy_id, started_at DESC)"
    )

    # ------------------------------------------------------- agent readiness
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_readiness (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            overall VARCHAR(12) NOT NULL DEFAULT 'LOW',
            score DOUBLE PRECISION NOT NULL DEFAULT 0,
            dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, agent_id)
        )
        """
    )


def downgrade() -> None:
    for table in (
        "agent_readiness",
        "spider_runs",
        "spider_policies",
        "source_conflicts",
        "learning_replays",
        "approval_records",
        "improvement_items",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_gap_type_check "
        "CHECK (gap_type IN ('CONTEXT_MISSING','DATA_MISSING','UNDEFINED_ENUM'))"
    )
    op.execute(
        "ALTER TABLE context_gaps DROP COLUMN IF EXISTS question, "
        "DROP COLUMN IF EXISTS impact, DROP COLUMN IF EXISTS resolved_by, "
        "DROP COLUMN IF EXISTS resolved_at"
    )
    op.execute("ALTER TABLE intelligence_traces DROP COLUMN IF EXISTS user_id")
    op.execute(
        "ALTER TABLE catalog_lineage DROP CONSTRAINT IF EXISTS catalog_lineage_relation_check"
    )
    op.execute(
        "ALTER TABLE catalog_lineage ADD CONSTRAINT catalog_lineage_relation_check "
        "CHECK (relation IN ('DEFINES','USES','DEPENDS_ON','MAPS_TO',"
        "'IS_AUTHORITY_FOR','SOURCE_OF'))"
    )
    op.execute("ALTER TABLE catalog_enum_values DROP COLUMN IF EXISTS version")

"""Company Discovery Engine — candidatos y corridas.

Revision ID: 130
Revises: 129

Los candidatos son PROPUESTAS: nada aquí es verdad de la compañía hasta que
se valida y se promueve al Company Graph (migración 129). Tenant scoping
estricto; dedupe por (organization_id, kind, natural_key).
"""
from __future__ import annotations

from alembic import op

revision: str = "130"
down_revision: str = "129"
branch_labels = None
depends_on = None

_STAGES = (
    "('discovered','supported','suggested','validated','confirmed','rejected')"
)
_RUN_STATUS = "('pending','running','completed','failed')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS company_discovery_candidates (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            kind VARCHAR(32) NOT NULL,
            stage VARCHAR(24) NOT NULL DEFAULT 'discovered'
                CHECK (stage IN {_STAGES}),
            natural_key VARCHAR(600) NOT NULL,
            title VARCHAR(320) NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            payload JSONB NOT NULL DEFAULT '{{}}',
            source_kind VARCHAR(32) NOT NULL,
            source_ref VARCHAR(512) NOT NULL DEFAULT '',
            discovered_by VARCHAR(120) NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0
                CHECK (confidence >= 0 AND confidence <= 1),
            confidence_factors JSONB NOT NULL DEFAULT '{{}}',
            support JSONB NOT NULL DEFAULT '{{}}',
            evidence JSONB NOT NULL DEFAULT '[]',
            resolution JSONB NOT NULL DEFAULT '{{}}',
            reviewed_by UUID,
            reviewed_at TIMESTAMPTZ,
            materialized_id UUID,
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, kind, natural_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_candidates_org_kind_stage
        ON company_discovery_candidates (organization_id, kind, stage)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_candidates_org_stage_conf
        ON company_discovery_candidates (organization_id, stage, confidence DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_candidates_org_source
        ON company_discovery_candidates (organization_id, source_kind)
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS company_discovery_runs (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            trigger VARCHAR(24) NOT NULL DEFAULT 'manual',
            status VARCHAR(24) NOT NULL DEFAULT 'pending'
                CHECK (status IN {_RUN_STATUS}),
            source_kinds JSONB NOT NULL DEFAULT '[]',
            candidates_found INT NOT NULL DEFAULT 0,
            candidates_new INT NOT NULL DEFAULT 0,
            candidates_updated INT NOT NULL DEFAULT 0,
            promoted INT NOT NULL DEFAULT 0,
            conflicts INT NOT NULL DEFAULT 0,
            metrics JSONB NOT NULL DEFAULT '{{}}',
            error TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            duration_ms INT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_discovery_runs_org
        ON company_discovery_runs (organization_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_discovery_runs_status
        ON company_discovery_runs (status, created_at)
        WHERE status IN ('pending','running')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_discovery_runs")
    op.execute("DROP TABLE IF EXISTS company_discovery_candidates")

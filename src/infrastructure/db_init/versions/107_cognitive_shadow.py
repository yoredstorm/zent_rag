"""Cognitive shadow runs — Phase 8.

cognitive_shadow_runs guarda la comparación baseline vs cognitive por query
(métricas + veredicto). No altera la respuesta visible.

Revision ID: 107
Revises: 106
"""
from __future__ import annotations

from alembic import op

revision: str = "107"
down_revision: str = "106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cognitive_shadow_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            query TEXT NOT NULL,
            complexity VARCHAR(2) NOT NULL CHECK (complexity IN ('L0','L1','L2','L3','L4','L5')),
            baseline_run_id UUID,
            cognitive_run_id UUID,
            baseline_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            cognitive_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
            verdict VARCHAR(24) NOT NULL
                CHECK (verdict IN ('cognitive_better','baseline_better','tie')),
            reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_cognitive_shadow_org_created "
        "ON cognitive_shadow_runs(organization_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cognitive_shadow_runs")

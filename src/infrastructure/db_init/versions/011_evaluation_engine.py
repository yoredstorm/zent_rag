"""Evaluation Engine — datasets, runs y resultados por caso.

Revision ID: 011
Revises: 010
Create Date: 2026-08-22

Persistencia del engine de evaluación:
  - eval_datasets: golden sets importados (schema v2).
  - eval_runs: runs de evaluación con version_snapshot (prompt, model,
    embedding, chunking, retriever, reranker) y summary JSONB.
  - eval_case_results: métricas y scores por caso (cascada al borrar run).
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_datasets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 2,
            cases JSONB NOT NULL DEFAULT '[]',
            weights JSONB NOT NULL DEFAULT '{}',
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_datasets_org "
        "ON eval_datasets(organization_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_runs (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            dataset_id UUID,
            dataset_name TEXT,
            target_type VARCHAR(10) NOT NULL,
            target_id UUID,
            target_name TEXT,
            version_snapshot JSONB NOT NULL DEFAULT '{}',
            version_id TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            summary JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_org "
        "ON eval_runs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_version "
        "ON eval_runs(version_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_case_results (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            case_id TEXT NOT NULL,
            question TEXT,
            answer TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            target JSONB NOT NULL DEFAULT '{}',
            metrics JSONB NOT NULL DEFAULT '{}',
            scores JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_cases_run "
        "ON eval_case_results(run_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_case_results")
    op.execute("DROP TABLE IF EXISTS eval_runs")
    op.execute("DROP TABLE IF EXISTS eval_datasets")

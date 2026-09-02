"""Evals v2 — datasets versionados, runs con gate, regresión.

Nota: eval_datasets/eval_runs ya existen desde PROMPT 04 (schema de casos
JSON); v2 usa tablas propias con items relacionales.

Revision ID: 044
Revises: 043
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_v2_datasets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            version INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_v2_datasets_org "
        "ON eval_v2_datasets(organization_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_v2_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            dataset_id UUID NOT NULL,
            question TEXT NOT NULL,
            expected_answer TEXT NOT NULL,
            context TEXT,
            score_weight DOUBLE PRECISION NOT NULL DEFAULT 1.0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_v2_items_dataset "
        "ON eval_v2_items(dataset_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_v2_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            dataset_id UUID NOT NULL,
            dataset_version INT NOT NULL,
            agent_id UUID NOT NULL,
            agent_version_id UUID,
            model VARCHAR(120),
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            score_overall DOUBLE PRECISION,
            faithfulness DOUBLE PRECISION,
            hallucination_rate DOUBLE PRECISION,
            latency_p95 DOUBLE PRECISION,
            cost_total DOUBLE PRECISION,
            passed_gate BOOLEAN,
            regression BOOLEAN NOT NULL DEFAULT false,
            created_by UUID,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_v2_runs_org "
        "ON eval_v2_runs(organization_id, started_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_v2_run_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            item_id UUID,
            question TEXT NOT NULL,
            answer TEXT,
            expected_answer TEXT NOT NULL,
            score DOUBLE PRECISION,
            faithfulness DOUBLE PRECISION,
            hallucination_rate DOUBLE PRECISION,
            latency_ms DOUBLE PRECISION,
            cost DOUBLE PRECISION
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_v2_run_items_run "
        "ON eval_v2_run_items(run_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_eval_v2_run_items_run")
    op.execute("DROP TABLE IF EXISTS eval_v2_run_items")
    op.execute("DROP INDEX IF EXISTS idx_eval_v2_runs_org")
    op.execute("DROP TABLE IF EXISTS eval_v2_runs")
    op.execute("DROP INDEX IF EXISTS idx_eval_v2_items_dataset")
    op.execute("DROP TABLE IF EXISTS eval_v2_items")
    op.execute("DROP INDEX IF EXISTS idx_eval_v2_datasets_org")
    op.execute("DROP TABLE IF EXISTS eval_v2_datasets")

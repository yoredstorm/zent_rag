"""Evaluation Engine — eval_examples como entidad de primer nivel.

Revision ID: 026
Revises: 025
Create Date: 2026-08-31
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_examples (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            dataset_id UUID NOT NULL REFERENCES eval_datasets(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            expected_answer TEXT,
            expected_behavior VARCHAR(80),
            expected_sources JSONB NOT NULL DEFAULT '[]',
            must_cite BOOLEAN NOT NULL DEFAULT false,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_examples_dataset "
        "ON eval_examples(dataset_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_examples_org "
        "ON eval_examples(organization_id)"
    )
    # Backfill: migra los casos JSONB existentes a la tabla de examples.
    op.execute(
        """
        INSERT INTO eval_examples (
            id, organization_id, dataset_id, question, expected_answer,
            expected_behavior, expected_sources, must_cite, metadata
        )
        SELECT gen_random_uuid(), d.organization_id, d.id,
               c.value ->> 'question',
               c.value ->> 'expected_answer',
               c.value ->> 'expected_behavior',
               COALESCE(c.value -> 'expected_sources', '[]'::jsonb),
               COALESCE((c.value ->> 'must_cite')::boolean, false),
               COALESCE(c.value -> 'metadata', '{}'::jsonb)
        FROM eval_datasets d
        CROSS JOIN LATERAL jsonb_array_elements(d.cases) c(value)
        WHERE (c.value ->> 'question') IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS eval_examples")

"""Multitenant LLM Proxy — inference_models, inference_logs, deployment rules.

Revision ID: 046
Revises: 045
Create Date: 2026-09-01
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inference_models (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            model_name VARCHAR(120) NOT NULL UNIQUE,
            backend VARCHAR(20) NOT NULL DEFAULT 'openai',
            capacity INT NOT NULL DEFAULT 50,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        INSERT INTO inference_models (model_name, backend, capacity) VALUES
        ('gpt-4o-mini', 'openai', 50),
        ('gpt-4o', 'openai', 10),
        ('zent-cheap', 'vllm', 100),
        ('zent-fast', 'tgi', 200)
        ON CONFLICT (model_name) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS inference_logs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            deployment_id UUID,
            agent_id UUID,
            model VARCHAR(120) NOT NULL,
            backend VARCHAR(20),
            status VARCHAR(20) NOT NULL DEFAULT 'completed',
            prompt_tokens INT NOT NULL DEFAULT 0,
            completion_tokens INT NOT NULL DEFAULT 0,
            total_tokens INT NOT NULL DEFAULT 0,
            latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            queue_wait_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inference_logs_org_time "
        "ON inference_logs(organization_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inference_logs_model_time "
        "ON inference_logs(model, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_inference_logs_dep_time "
        "ON inference_logs(deployment_id, created_at DESC)"
    )
    op.execute(
        "ALTER TABLE rate_limit_rules ADD COLUMN IF NOT EXISTS "
        "deployment_id UUID"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inference_logs")
    op.execute("DROP TABLE IF EXISTS inference_models")
    op.execute("ALTER TABLE rate_limit_rules DROP COLUMN IF EXISTS deployment_id")

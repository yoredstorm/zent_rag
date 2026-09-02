"""Agent versions — snapshot inmutable de configuracion de agentes.

Revision ID: 021
Revises: 020
Create Date: 2026-08-30
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'ready', 'staging', 'production', 'archived')),
            config_snapshot JSONB NOT NULL DEFAULT '{}',
            notes TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (agent_id, version_number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_versions_agent "
        "ON agent_versions(agent_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_versions_org "
        "ON agent_versions(organization_id)"
    )
    # Identidad del agente: slug unico por organizacion + estado del ciclo de vida.
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS slug VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
        "NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_org_slug "
        "ON agents(organization_id, slug) WHERE slug IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_org_status ON agents(organization_id, status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS agent_versions")
    op.execute("DROP INDEX IF EXISTS idx_agents_org_status")
    op.execute("DROP INDEX IF EXISTS idx_agents_org_slug")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS slug")

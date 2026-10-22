"""Universal Studio — role profiles and solution blueprints.

Revision ID: 163
Revises: 162

Aditiva:
- role_profiles + role_profile_versions;
- studio_solutions + studio_solution_versions;
- agents.role_profile_id (nullable; no rewrites, no second agent table).

No secrets, tenant IDs or provider IDs live in a portable role/solution
contract. The runtime still uses agents, workflows and workflow_instances.
"""
from __future__ import annotations

from alembic import op

revision: str = "163"
down_revision: str = "162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS role_profiles (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            slug VARCHAR(80) NOT NULL,
            name VARCHAR(150) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            mission TEXT NOT NULL DEFAULT '',
            audience JSONB NOT NULL DEFAULT '[]'::jsonb,
            tone JSONB NOT NULL DEFAULT '[]'::jsonb,
            competencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            constraints JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
            denied_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
            allowed_tools JSONB NOT NULL DEFAULT '[]'::jsonb,
            knowledge_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
            memory_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
            autonomy_level VARCHAR(30) NOT NULL DEFAULT 'propose_actions',
            human_handoff JSONB NOT NULL DEFAULT '{}'::jsonb,
            expected_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            evaluation_rubric JSONB NOT NULL DEFAULT '[]'::jsonb,
            risk_class VARCHAR(20) NOT NULL DEFAULT 'low',
            locales JSONB NOT NULL DEFAULT '["es"]'::jsonb,
            compliance_tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            safety JSONB NOT NULL DEFAULT '{}'::jsonb,
            version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
            revision INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_role_profiles_org
        ON role_profiles(organization_id, workspace_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS role_profile_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            role_profile_id UUID NOT NULL REFERENCES role_profiles(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            version VARCHAR(20) NOT NULL,
            revision INT NOT NULL,
            snapshot JSONB NOT NULL,
            notes TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (role_profile_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_role_profile_versions_role
        ON role_profile_versions(role_profile_id, revision DESC)
        """
    )
    op.execute(
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS role_profile_id UUID"
    )
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE agents
                ADD CONSTRAINT fk_agents_role_profile_id
                FOREIGN KEY (role_profile_id)
                REFERENCES role_profiles(id)
                ON DELETE SET NULL;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS studio_solutions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            slug VARCHAR(80) NOT NULL,
            name VARCHAR(150) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            blueprint JSONB NOT NULL,
            version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
            revision INT NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, slug)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_studio_solutions_org
        ON studio_solutions(organization_id, workspace_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS studio_solution_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            solution_id UUID NOT NULL REFERENCES studio_solutions(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL,
            version VARCHAR(20) NOT NULL,
            revision INT NOT NULL,
            snapshot JSONB NOT NULL,
            notes TEXT,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (solution_id, revision)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_studio_solution_versions_solution
        ON studio_solution_versions(solution_id, revision DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS studio_solution_versions")
    op.execute("DROP TABLE IF EXISTS studio_solutions")
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_role_profile_id"
    )
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS role_profile_id")
    op.execute("DROP TABLE IF EXISTS role_profile_versions")
    op.execute("DROP TABLE IF EXISTS role_profiles")

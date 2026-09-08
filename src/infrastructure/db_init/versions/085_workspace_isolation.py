"""PHASE 31C — Workspace isolation (kind, active workspace, source scoping).

Revision ID: 085
Revises: 084
"""
from __future__ import annotations

from alembic import op

revision: str = "085"
down_revision: str = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workspaces
            ADD COLUMN IF NOT EXISTS kind VARCHAR(20) NOT NULL DEFAULT 'business'
        """
    )
    op.execute("ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_kind_check")
    op.execute(
        """
        ALTER TABLE workspaces
            ADD CONSTRAINT workspaces_kind_check
            CHECK (kind IN ('demo', 'business'))
        """
    )
    op.execute(
        """
        ALTER TABLE memberships
            ADD COLUMN IF NOT EXISTS active_workspace_id UUID
            REFERENCES workspaces(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_memberships_active_workspace "
        "ON memberships(active_workspace_id)"
    )
    op.execute(
        """
        ALTER TABLE kb_sources
            ADD COLUMN IF NOT EXISTS workspace_id UUID
            REFERENCES workspaces(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_kb_sources_workspace "
        "ON kb_sources(organization_id, workspace_id)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.catalog_sources') IS NOT NULL THEN
                ALTER TABLE catalog_sources ADD COLUMN IF NOT EXISTS workspace_id UUID;
                CREATE INDEX IF NOT EXISTS idx_catalog_sources_workspace
                    ON catalog_sources(organization_id, workspace_id);
                UPDATE catalog_sources cs
                SET workspace_id = w.id
                FROM workspaces w
                WHERE cs.workspace_id IS NULL
                  AND w.organization_id = cs.organization_id
                  AND w.slug = 'default';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        UPDATE kb_sources ks
        SET workspace_id = w.id
        FROM workspaces w
        WHERE ks.workspace_id IS NULL
          AND w.organization_id = ks.organization_id
          AND w.slug = 'default'
        """
    )
    op.execute(
        """
        UPDATE catalog_sources cs
        SET workspace_id = w.id
        FROM workspaces w
        WHERE cs.workspace_id IS NULL
          AND w.organization_id = cs.organization_id
          AND w.slug = 'default'
        """
    )
    op.execute(
        """
        UPDATE workspaces w
        SET kind = 'demo'
        WHERE w.slug = 'default'
          AND EXISTS (
              SELECT 1 FROM knowledge_bases kb
              WHERE kb.organization_id = w.organization_id
                AND (kb.name ILIKE '%demo%' OR kb.name ILIKE '%farmacia%')
          )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE catalog_sources DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE kb_sources DROP COLUMN IF EXISTS workspace_id")
    op.execute("ALTER TABLE memberships DROP COLUMN IF EXISTS active_workspace_id")
    op.execute("ALTER TABLE workspaces DROP CONSTRAINT IF EXISTS workspaces_kind_check")
    op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS kind")

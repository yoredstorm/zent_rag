"""Solution materializations — idempotent compile/materialize artifacts.

Revision ID: 167
Revises: 166

Aditiva. Guarda la compilación server-side y los recursos creados/reutilizados.
El blueprint de `studio_solutions` sigue siendo portable (sin IDs físicos).
"""
from __future__ import annotations

from alembic import op

revision: str = "167"
down_revision: str = "166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS studio_solution_materializations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL,
            workspace_id UUID,
            solution_id UUID REFERENCES studio_solutions(id) ON DELETE SET NULL,
            idempotency_key VARCHAR(200) NOT NULL,
            compilation_hash VARCHAR(64) NOT NULL,
            template_id VARCHAR(80) NOT NULL DEFAULT '',
            status VARCHAR(30) NOT NULL DEFAULT 'IN_PROGRESS',
            compilation JSONB NOT NULL DEFAULT '{}'::jsonb,
            artifacts JSONB NOT NULL DEFAULT '{}'::jsonb,
            requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
            error VARCHAR(400),
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, idempotency_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_solution_materializations_solution "
        "ON studio_solution_materializations(organization_id, solution_id, updated_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_solution_materializations_hash "
        "ON studio_solution_materializations(organization_id, compilation_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_solution_materializations_hash")
    op.execute("DROP INDEX IF EXISTS idx_solution_materializations_solution")
    op.execute("DROP TABLE IF EXISTS studio_solution_materializations")

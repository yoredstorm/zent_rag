"""Workflow Semantic Core — contexto compartido por run (Fase 7).

- workflow_context_contributions: contribuciones inmutables por nodo (append).
- workflow_run_contexts: proyección JSONB del contexto del run (sin `security`).

No copia evidencia/claims: solo referencias validadas por organización.
"""
from __future__ import annotations

from alembic import op

revision: str = "115"
down_revision: str = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_context_contributions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id UUID NOT NULL,
            organization_id UUID NOT NULL,
            node_id VARCHAR(80) NOT NULL,
            node_type VARCHAR(40) NOT NULL,
            section VARCHAR(40) NOT NULL,
            value_type VARCHAR(40) NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            provenance JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_contrib_run "
        "ON workflow_context_contributions(run_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_contrib_org "
        "ON workflow_context_contributions(organization_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_run_contexts (
            run_id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            workspace_id UUID,
            schema_version INTEGER NOT NULL DEFAULT 1,
            context JSONB NOT NULL DEFAULT '{}',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_wf_run_contexts_org "
        "ON workflow_run_contexts(organization_id, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_wf_run_contexts_org")
    op.execute("DROP TABLE IF EXISTS workflow_run_contexts")
    op.execute("DROP INDEX IF EXISTS idx_wf_contrib_org")
    op.execute("DROP INDEX IF EXISTS idx_wf_contrib_run")
    op.execute("DROP TABLE IF EXISTS workflow_context_contributions")

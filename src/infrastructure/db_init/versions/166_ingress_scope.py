"""Scope ingress idempotency per workflow.

Revision ID: 166
Revises: 165

La misma clave externa puede llegar a dos workflows distintos; el inbox debe
deduplicar por workflow, no por tenant global.
"""
from __future__ import annotations

from alembic import op

revision: str = "166"
down_revision: str = "165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workflow_ingress_events "
        "DROP CONSTRAINT IF EXISTS workflow_ingress_events_organization_id_ingress_key_key"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_ingress_workflow_key "
        "ON workflow_ingress_events(organization_id, workflow_id, ingress_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_wf_ingress_workflow_key")
    op.execute(
        "ALTER TABLE workflow_ingress_events "
        "ADD CONSTRAINT workflow_ingress_events_organization_id_ingress_key_key "
        "UNIQUE (organization_id, ingress_key)"
    )

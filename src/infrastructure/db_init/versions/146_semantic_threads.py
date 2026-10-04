"""Progressive Semantic Ingestion — threads semánticos durables (Fase 4).

``knowledge_semantic_threads``: una fila por hilo semántico de un documento.
Un hilo representa continuidad bidireccional: una referencia/símbolo/
continuación/excepción que se abre en una ventana y puede resolverse muchas
ventanas después (o quedar OPEN/AMBIGUOUS).

- id determinista por (documento, thread_key);
- type REFERENCE/CONTINUATION/DEFINITION/SYMBOL/RULE_DEPENDENCY/
  TABLE_REFERENCE/EXCEPTION/ALIAS/TEMPORAL/ENTITY;
- status OPEN/PARTIAL/RESOLVED/AMBIGUOUS/CONFLICTING/UNRESOLVED;
- source_units + source_windows (provenance), resolved_by_unit,
  candidates (desambiguación), history (auditoría), confidence.

Aditiva: no toca tablas existentes.

Revision ID: 146
Revises: 145
"""
from __future__ import annotations

from alembic import op

revision: str = "146"
down_revision: str = "145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_semantic_threads (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            thread_key VARCHAR(200) NOT NULL,
            thread_type VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
            target_hint VARCHAR(512) NOT NULL DEFAULT '',
            target_kind VARCHAR(40),
            scope VARCHAR(200),
            source_units JSONB NOT NULL DEFAULT '[]',
            source_windows JSONB NOT NULL DEFAULT '[]',
            opened_at_window INTEGER NOT NULL DEFAULT 0,
            last_seen_window INTEGER NOT NULL DEFAULT 0,
            resolved_at_window INTEGER,
            resolved_by_unit VARCHAR(120),
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            candidates JSONB NOT NULL DEFAULT '[]',
            evidence JSONB NOT NULL DEFAULT '{}',
            history JSONB NOT NULL DEFAULT '[]',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, thread_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_threads_org_doc_status "
        "ON knowledge_semantic_threads(organization_id, document_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_threads_org_doc_type "
        "ON knowledge_semantic_threads(organization_id, document_id, thread_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_semantic_threads")

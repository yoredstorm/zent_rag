"""Knowledge V2 — Document versioning (Phase D/G, brief §40).

structured_document_versions registra cada cambio contenido (hash): created /
unchanged / updated / replaced, con versionado SQL por documento y puntero al
padre. La invalidación de embeddings/summaries/facts dependientes se gestiona
en fases posteriores a partir de change_kind. Head: 099.

Revision ID: 100
Revises: 099
"""
from __future__ import annotations

from alembic import op

revision: str = "100"
down_revision: str = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS structured_document_versions (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            document_id UUID NOT NULL
                REFERENCES structured_documents(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            version INTEGER NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            change_kind VARCHAR(12) NOT NULL
                CHECK (change_kind IN ('created','unchanged','updated','replaced')),
            previous_version_id UUID,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_structured_doc_versions_org_doc "
        "ON structured_document_versions(organization_id, document_id, version)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS structured_document_versions")

"""Progressive Semantic Ingestion — Semantic Fabric (Fase 8).

Tres tablas:

1. ``knowledge_fabric_nodes``: nodos del fabric (Entity, Concept, Definition,
   Claim, Rule, Condition, Exception, Procedure, Metric, Attribute, Symbol,
   TableSemantic, TemporalAssertion, Reference, Evidence) con provenance a
   unit_key/block_ids/ventanas.
2. ``knowledge_fabric_edges``: aristas tipadas del vocabulario §21 con
   evidencia y confianza.
3. ``knowledge_fabric_identities``: candidatos de identidad cross-source
   (same_identity/likely_identity/alias_candidate/related_concept). El fabric
   NUNCA fusiona por similitud; solo propone con evidencia.

Revision ID: 150
Revises: 149
"""
from __future__ import annotations

from alembic import op

revision: str = "150"
down_revision: str = "149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_fabric_nodes (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            node_key VARCHAR(400) NOT NULL,
            node_type VARCHAR(30) NOT NULL,
            label VARCHAR(300) NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            scope VARCHAR(30) NOT NULL DEFAULT 'document',
            unit_key VARCHAR(300) NOT NULL DEFAULT '',
            block_ids JSONB NOT NULL DEFAULT '[]',
            windows JSONB NOT NULL DEFAULT '[]',
            attributes JSONB NOT NULL DEFAULT '{}',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, node_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_nodes_org_doc_type "
        "ON knowledge_fabric_nodes(organization_id, document_id, node_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_nodes_org_label "
        "ON knowledge_fabric_nodes(organization_id, lower(label))"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_fabric_edges (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            document_id UUID NOT NULL,
            edge_key VARCHAR(800) NOT NULL,
            relation_type VARCHAR(40) NOT NULL,
            subject_id UUID NOT NULL,
            object_id UUID NOT NULL,
            subject_key VARCHAR(400) NOT NULL DEFAULT '',
            object_key VARCHAR(400) NOT NULL DEFAULT '',
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            method VARCHAR(40) NOT NULL DEFAULT 'deterministic',
            evidence JSONB NOT NULL DEFAULT '[]',
            windows JSONB NOT NULL DEFAULT '[]',
            attributes JSONB NOT NULL DEFAULT '{}',
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, document_id, edge_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_edges_org_doc_type "
        "ON knowledge_fabric_edges(organization_id, document_id, relation_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_edges_org_subject "
        "ON knowledge_fabric_edges(organization_id, subject_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_edges_org_object "
        "ON knowledge_fabric_edges(organization_id, object_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_fabric_identities (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            left_node_id UUID NOT NULL,
            right_node_id UUID NOT NULL,
            left_key VARCHAR(400) NOT NULL DEFAULT '',
            right_key VARCHAR(400) NOT NULL DEFAULT '',
            left_label VARCHAR(300) NOT NULL DEFAULT '',
            right_label VARCHAR(300) NOT NULL DEFAULT '',
            left_document_id UUID,
            right_document_id UUID,
            left_source_id UUID,
            right_source_id UUID,
            identity_status VARCHAR(30) NOT NULL,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            reason VARCHAR(300) NOT NULL DEFAULT '',
            evidence JSONB NOT NULL DEFAULT '{}',
            temporal_compatible BOOLEAN NOT NULL DEFAULT true,
            scope_compatible BOOLEAN NOT NULL DEFAULT true,
            version VARCHAR(60) NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, left_node_id, right_node_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_identities_org_status "
        "ON knowledge_fabric_identities(organization_id, identity_status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_identities_org_left "
        "ON knowledge_fabric_identities(organization_id, left_document_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_fabric_identities_org_right "
        "ON knowledge_fabric_identities(organization_id, right_document_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_fabric_identities")
    op.execute("DROP TABLE IF EXISTS knowledge_fabric_edges")
    op.execute("DROP TABLE IF EXISTS knowledge_fabric_nodes")

"""Phase 31A — Data Onboarding: hechos de documentos y revisión humana.

Permite catalog_suggestions.type = 'document_fact' y crea document_insights
(insights extraídos de contratos/documentos, nada se auto-aprueba).

Revision ID: 093
Revises: 092
"""
from __future__ import annotations

from alembic import op

revision: str = "093"
down_revision: str = "092"
branch_labels = None
depends_on = None

_TYPES = (
    "('entity_identification','table_identification',"
    "'relationship_candidate','enum_definition','field_mapping',"
    "'metric_proposal','glossary_term','document_fact')"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "DROP CONSTRAINT IF EXISTS catalog_suggestions_type_check"
    )
    op.execute(
        "ALTER TABLE catalog_suggestions "
        f"ADD CONSTRAINT catalog_suggestions_type_check CHECK (type IN {_TYPES})"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_insights (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            session_id UUID,
            source_id UUID,
            insight_type VARCHAR(40) NOT NULL,
            key VARCHAR(200) NOT NULL,
            value TEXT NOT NULL,
            normalized_value TEXT,
            evidence TEXT,
            page INTEGER,
            confidence VARCHAR(10) NOT NULL DEFAULT 'medium',
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            reviewed_by UUID,
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_insights_org_source "
        "ON document_insights(organization_id, source_id, status)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "DROP CONSTRAINT IF EXISTS catalog_suggestions_type_check"
    )
    op.execute(
        "ALTER TABLE catalog_suggestions "
        "ADD CONSTRAINT catalog_suggestions_type_check CHECK (type IN "
        "('entity_identification','table_identification','relationship_candidate',"
        "'enum_definition','field_mapping','metric_proposal','glossary_term'))"
    )
    op.execute("DROP TABLE IF EXISTS document_insights")

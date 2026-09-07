"""PHASE 26C — Verified Query Repository + mapping suggestions.

Revision ID: 082
Revises: 081
"""
from __future__ import annotations

from alembic import op

revision: str = "082"
down_revision: str = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS verified_queries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            canonical_question TEXT NOT NULL,
            question_variants JSONB NOT NULL DEFAULT '[]'::jsonb,
            semantic_ast JSONB NOT NULL DEFAULT '{}'::jsonb,
            verified_sql TEXT NOT NULL,
            dialect VARCHAR(40) NOT NULL DEFAULT 'postgres',
            source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            table_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            column_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            metric_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            concept_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'DRAFT'
                CHECK (status IN ('DRAFT','IN_REVIEW','VERIFIED','DEPRECATED','INVALID')),
            version INT NOT NULL DEFAULT 1,
            approved_by UUID,
            approved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_verified_at TIMESTAMPTZ,
            execution_fingerprint VARCHAR(128)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_verified_queries_org_status "
        "ON verified_queries(organization_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS verified_query_versions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            verified_query_id UUID NOT NULL REFERENCES verified_queries(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            version INT NOT NULL,
            snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (verified_query_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mapping_suggestions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            concept VARCHAR(160) NOT NULL,
            entity_type VARCHAR(40) NOT NULL DEFAULT 'ENTITY',
            physical_predicate TEXT NOT NULL,
            evidence_count INT NOT NULL DEFAULT 0,
            evidence_sample JSONB NOT NULL DEFAULT '[]'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'INFERRED'
                CHECK (status IN ('INFERRED','APPROVED','REJECTED','EDITED_APPROVED')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_by UUID,
            reviewed_at TIMESTAMPTZ,
            UNIQUE (organization_id, concept, physical_predicate)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mapping_suggestions")
    op.execute("DROP TABLE IF EXISTS verified_query_versions")
    op.execute("DROP TABLE IF EXISTS verified_queries")

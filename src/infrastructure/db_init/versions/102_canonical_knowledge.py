"""Canonical Knowledge Model — identity registry + mapping (Phase 1).

knowledge_canonical_objects guarda la identidad canónica (UUID determinista
por org+kind+natural_key). knowledge_canonical_links mapea objetos físicos de
los sistemas existentes (V1, V2, catalog, KLE, data onboarding, Hub) al
canónico. Puro aditivo: ningún camino productivo lee estas tablas.

Revision ID: 102
Revises: 101
"""
from __future__ import annotations

from alembic import op

revision: str = "102"
down_revision: str = "101"
branch_labels = None
depends_on = None

_KINDS = (
    "'source','document','section','block','chunk','entity','fact','rule',"
    "'metric','glossary_term','relationship','question','claim','evidence','artifact'"
)
_SYSTEMS = (
    "'v1_knowledge_platform','v1_document_registry','v2_structured','catalog',"
    "'knowledge_learning','governed_learning','data_onboarding','knowledge_hub',"
    "'intelligence'"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_canonical_objects (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            kind VARCHAR(32) NOT NULL CHECK (kind IN ({_KINDS})),
            natural_key VARCHAR(768) NOT NULL,
            title VARCHAR(512) NOT NULL DEFAULT '',
            provenance VARCHAR(16) NOT NULL DEFAULT 'OBSERVED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            status VARCHAR(16) NOT NULL DEFAULT 'observed'
                CHECK (status IN ('draft','observed','inferred','approved','rejected','archived')),
            confidence DOUBLE PRECISION,
            authority_level VARCHAR(32),
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, kind, natural_key),
            CONSTRAINT ck_canonical_approval_law
                CHECK (status <> 'approved' OR provenance = 'APPROVED')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_kind "
        "ON knowledge_canonical_objects(organization_id, kind)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_objects_org_updated "
        "ON knowledge_canonical_objects(organization_id, updated_at)"
    )
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS knowledge_canonical_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_id UUID NOT NULL
                REFERENCES knowledge_canonical_objects(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            system VARCHAR(32) NOT NULL CHECK (system IN ({_SYSTEMS})),
            object_type VARCHAR(64) NOT NULL,
            object_ref VARCHAR(512) NOT NULL,
            is_primary BOOLEAN NOT NULL DEFAULT false,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, system, object_type, object_ref)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_links_org_canonical "
        "ON knowledge_canonical_links(organization_id, canonical_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_links_primary "
        "ON knowledge_canonical_links(canonical_id) WHERE is_primary"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_canonical_links")
    op.execute("DROP TABLE IF EXISTS knowledge_canonical_objects")

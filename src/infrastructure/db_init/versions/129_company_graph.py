"""Company Intelligence Graph — entities + relationships + source authority.

Revision ID: 129
Revises: 128

GRAPH-FIRST pero STORAGE-AGNOSTIC: Postgres es el backend inicial
(transactional truth). Tablas extensibles por tipo (columna entity_type /
relationship_type, sin proliferación de tablas). Tenant scoping estricto.
Temporalidad semiabierta [valid_from, valid_to).
"""
from __future__ import annotations

from alembic import op

revision: str = "129"
down_revision: str = "128"
branch_labels = None
depends_on = None

_ENTITY_STATUS = (
    "('discovered','supported','confirmed','contradicted',"
    "'deprecated','stale','rejected','auto_confirmed')"
)
_AUTHORITY = (
    "('authoritative','primary','secondary','informational','untrusted')"
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS company_entities (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            entity_type VARCHAR(64) NOT NULL,
            canonical_name VARCHAR(320) NOT NULL,
            display_name VARCHAR(320) NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            domain VARCHAR(120) NOT NULL DEFAULT 'general',
            aliases JSONB NOT NULL DEFAULT '[]',
            status VARCHAR(24) NOT NULL DEFAULT 'discovered'
                CHECK (status IN {_ENTITY_STATUS}),
            confidence DOUBLE PRECISION,
            authority_level VARCHAR(16)
                CHECK (authority_level IN {_AUTHORITY}),
            source VARCHAR(200) NOT NULL DEFAULT '',
            source_ref VARCHAR(512) NOT NULL DEFAULT '',
            evidence JSONB NOT NULL DEFAULT '[]',
            metadata JSONB NOT NULL DEFAULT '{{}}',
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, entity_type, canonical_name),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_entities_org_type
        ON company_entities (organization_id, entity_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_entities_org_name
        ON company_entities (organization_id, canonical_name)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_entities_org_current
        ON company_entities (organization_id, status)
        WHERE status NOT IN ('deprecated','rejected')
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_entities_org_domain
        ON company_entities (organization_id, domain)
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS company_relationships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            from_entity_id UUID NOT NULL REFERENCES company_entities(id) ON DELETE CASCADE,
            to_entity_id UUID NOT NULL REFERENCES company_entities(id) ON DELETE CASCADE,
            relationship_type VARCHAR(64) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'discovered'
                CHECK (status IN {_ENTITY_STATUS}),
            confidence DOUBLE PRECISION,
            source VARCHAR(200) NOT NULL DEFAULT '',
            source_ref VARCHAR(512) NOT NULL DEFAULT '',
            evidence_refs JSONB NOT NULL DEFAULT '[]',
            metadata JSONB NOT NULL DEFAULT '{{}}',
            valid_from TIMESTAMPTZ,
            valid_to TIMESTAMPTZ,
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (from_entity_id <> to_entity_id),
            CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
            CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_rels_org_from
        ON company_relationships (organization_id, from_entity_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_rels_org_to
        ON company_relationships (organization_id, to_entity_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_rels_org_type
        ON company_relationships (organization_id, relationship_type)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_rels_org_current
        ON company_relationships (organization_id, status)
        WHERE status NOT IN ('deprecated','rejected')
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS company_source_authority (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            domain VARCHAR(120) NOT NULL DEFAULT 'general',
            concept VARCHAR(160) NOT NULL DEFAULT '',
            source_name VARCHAR(200) NOT NULL,
            source_type VARCHAR(20) NOT NULL DEFAULT 'connector'
                CHECK (source_type IN ('connector','document','api','database','manual')),
            authority_level VARCHAR(16) NOT NULL DEFAULT 'informational'
                CHECK (authority_level IN {_AUTHORITY}),
            priority INT NOT NULL DEFAULT 1,
            effective_from TIMESTAMPTZ,
            effective_to TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (organization_id, domain, concept, source_name)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_authority_org_domain
        ON company_source_authority (organization_id, domain, concept)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS company_source_authority")
    op.execute("DROP TABLE IF EXISTS company_relationships")
    op.execute("DROP TABLE IF EXISTS company_entities")

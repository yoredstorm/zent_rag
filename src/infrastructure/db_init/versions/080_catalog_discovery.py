"""PHASE 24 — Zent Discovery Engine & Semantic Catalog.

Revision ID: 080
Revises: 079
"""
from __future__ import annotations

from alembic import op

revision: str = "080"
down_revision: str = "079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ físico
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_sources (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            connector_id UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
            kb_source_id UUID,
            engine VARCHAR(30) NOT NULL DEFAULT '',
            phase VARCHAR(30) NOT NULL DEFAULT 'QUEUED'
                CHECK (phase IN ('QUEUED','SCANNING','PROFILING','INFERRING',
                                 'WAITING_REVIEW','COMPLETED','PARTIAL','FAILED','CANCELLED')),
            budgets JSONB NOT NULL DEFAULT '{}'::jsonb,
            last_scan_at TIMESTAMPTZ,
            next_scan_at TIMESTAMPTZ,
            scan_interval_hours INT NOT NULL DEFAULT 0,
            content_signature VARCHAR(64),
            scan_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, connector_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_sources_org "
        "ON catalog_sources(organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_sources_due "
        "ON catalog_sources(next_scan_at) WHERE next_scan_at IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_scans (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES catalog_sources(id) ON DELETE CASCADE,
            scan_type VARCHAR(20) NOT NULL DEFAULT 'initial'
                CHECK (scan_type IN ('initial','incremental','manual','scheduled')),
            status VARCHAR(20) NOT NULL DEFAULT 'completed'
                CHECK (status IN ('queued','running','completed','partial','failed','cancelled')),
            tables_scanned INT NOT NULL DEFAULT 0,
            changes JSONB NOT NULL DEFAULT '[]'::jsonb,
            error TEXT,
            duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_scans_source "
        "ON catalog_scans(source_id, created_at DESC)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_tables (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES catalog_sources(id) ON DELETE CASCADE,
            schema_name VARCHAR(128) NOT NULL DEFAULT '',
            table_name VARCHAR(128) NOT NULL,
            is_view BOOLEAN NOT NULL DEFAULT false,
            row_count_approx BIGINT,
            table_comment TEXT,
            indexes JSONB NOT NULL DEFAULT '[]'::jsonb,
            content_hash VARCHAR(64),
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            removed_at TIMESTAMPTZ,
            UNIQUE (organization_id, source_id, schema_name, table_name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_tables_source "
        "ON catalog_tables(source_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_columns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            table_id UUID NOT NULL REFERENCES catalog_tables(id) ON DELETE CASCADE,
            column_name VARCHAR(128) NOT NULL,
            ordinal_position INT NOT NULL DEFAULT 0,
            data_type VARCHAR(128) NOT NULL DEFAULT '',
            nullable BOOLEAN NOT NULL DEFAULT true,
            is_primary_key BOOLEAN NOT NULL DEFAULT false,
            column_default TEXT,
            column_comment TEXT,
            null_ratio DOUBLE PRECISION,
            cardinality_approx BIGINT,
            pii_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
            is_sensitive BOOLEAN NOT NULL DEFAULT false,
            sample_disabled BOOLEAN NOT NULL DEFAULT false,
            UNIQUE (organization_id, table_id, column_name)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_columns_table "
        "ON catalog_columns(table_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_relationships (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES catalog_sources(id) ON DELETE CASCADE,
            from_table_id UUID NOT NULL REFERENCES catalog_tables(id) ON DELETE CASCADE,
            from_column VARCHAR(128) NOT NULL,
            to_table_id UUID NOT NULL REFERENCES catalog_tables(id) ON DELETE CASCADE,
            to_column VARCHAR(128) NOT NULL,
            relation_type VARCHAR(20) NOT NULL DEFAULT 'foreign_key'
                CHECK (relation_type IN ('foreign_key','inferred')),
            confidence VARCHAR(10) NOT NULL DEFAULT 'high'
                CHECK (confidence IN ('high','medium','low')),
            status VARCHAR(20) NOT NULL DEFAULT 'suggested'
                CHECK (status IN ('suggested','confirmed','rejected')),
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            reviewed_by UUID,
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, from_table_id, from_column, to_table_id, to_column, relation_type)
        )
        """
    )
    # ----------------------------------------------------------------- semántico
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_entities (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name VARCHAR(160) NOT NULL,
            display_name VARCHAR(160) NOT NULL DEFAULT '',
            description TEXT,
            provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            confidence VARCHAR(10) NOT NULL DEFAULT 'low'
                CHECK (confidence IN ('high','medium','low')),
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            mapped_table_id UUID REFERENCES catalog_tables(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','approved','deprecated')),
            created_by UUID,
            approved_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_fields (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            entity_id UUID NOT NULL REFERENCES catalog_entities(id) ON DELETE CASCADE,
            name VARCHAR(160) NOT NULL,
            description TEXT,
            provenance VARCHAR(20) NOT NULL DEFAULT 'INFERRED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            confidence VARCHAR(10) NOT NULL DEFAULT 'low'
                CHECK (confidence IN ('high','medium','low')),
            mapped_column_id UUID REFERENCES catalog_columns(id) ON DELETE SET NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','approved','deprecated')),
            created_by UUID,
            approved_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, entity_id, name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_metrics (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            metric_key VARCHAR(160) NOT NULL,
            name VARCHAR(160) NOT NULL,
            definition TEXT NOT NULL,
            formula TEXT,
            semantic_dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
            physical_mappings JSONB NOT NULL DEFAULT '[]'::jsonb,
            filters JSONB NOT NULL DEFAULT '[]'::jsonb,
            time_semantics VARCHAR(40),
            currency_semantics VARCHAR(40),
            owner VARCHAR(120),
            status VARCHAR(20) NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','approved','deprecated')),
            version INT NOT NULL DEFAULT 1,
            definition_id UUID REFERENCES business_definitions(id) ON DELETE SET NULL,
            created_by UUID,
            approved_by UUID,
            effective_from TIMESTAMPTZ,
            effective_to TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, metric_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_authority (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            domain VARCHAR(120) NOT NULL DEFAULT 'general',
            concept VARCHAR(160) NOT NULL,
            source_name VARCHAR(200) NOT NULL,
            source_type VARCHAR(20) NOT NULL DEFAULT 'connector'
                CHECK (source_type IN ('connector','document','api')),
            connector_id UUID REFERENCES connectors(id) ON DELETE SET NULL,
            authority_level VARCHAR(20) NOT NULL DEFAULT 'authoritative'
                CHECK (authority_level IN ('authoritative','approved','informational','external')),
            priority INT NOT NULL DEFAULT 1,
            effective_from TIMESTAMPTZ,
            effective_to TIMESTAMPTZ,
            created_by UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, domain, concept, source_name)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_suggestions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            type VARCHAR(40) NOT NULL
                CHECK (type IN ('entity_identification','table_identification',
                                'relationship_candidate','enum_definition',
                                'field_mapping','metric_proposal','glossary_term')),
            title VARCHAR(300) NOT NULL,
            description TEXT,
            evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
            confidence VARCHAR(10) NOT NULL DEFAULT 'low'
                CHECK (confidence IN ('high','medium','low')),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected','deferred','edited_approved')),
            affected_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            affected_agents JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reviewed_by UUID,
            reviewed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_suggestions_org_status "
        "ON catalog_suggestions(organization_id, status)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_enum_values (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            column_id UUID NOT NULL REFERENCES catalog_columns(id) ON DELETE CASCADE,
            value VARCHAR(200) NOT NULL,
            occurrence_count INT NOT NULL DEFAULT 0,
            documented_meaning TEXT,
            provenance VARCHAR(20) NOT NULL DEFAULT 'OBSERVED'
                CHECK (provenance IN ('OBSERVED','INFERRED','APPROVED','REJECTED','DEPRECATED')),
            confidence VARCHAR(10) NOT NULL DEFAULT 'low'
                CHECK (confidence IN ('high','medium','low')),
            status VARCHAR(20) NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, column_id, value)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS catalog_lineage (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            upstream_type VARCHAR(40) NOT NULL,
            upstream_id VARCHAR(64) NOT NULL,
            downstream_type VARCHAR(40) NOT NULL,
            downstream_id VARCHAR(64) NOT NULL,
            relation VARCHAR(30) NOT NULL
                CHECK (relation IN ('DEFINES','USES','DEPENDS_ON','MAPS_TO',
                                    'IS_AUTHORITY_FOR','SOURCE_OF')),
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_lineage_org_up "
        "ON catalog_lineage(organization_id, upstream_type, upstream_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalog_lineage_org_down "
        "ON catalog_lineage(organization_id, downstream_type, downstream_id)"
    )

    # ---------------------------------------------------------- ALTER (FASE 23)
    # Glosario: business_definitions gana campos de glossary governance.
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS synonyms JSONB NOT NULL DEFAULT '[]'::jsonb"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS owner VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS version INT NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS approved_by UUID"
    )
    op.execute(
        "ALTER TABLE business_definitions "
        "ADD COLUMN IF NOT EXISTS provenance VARCHAR(20) NOT NULL DEFAULT 'APPROVED'"
    )

    # Gaps: UNDEFINED_ENUM (columnas categóricas sin documentación).
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_gap_type_check "
        "CHECK (gap_type IN ('CONTEXT_MISSING','DATA_MISSING','UNDEFINED_ENUM'))"
    )

    # Jobs: estado 'partial' (scan completado con errores/presupuesto agotado).
    op.execute(
        "ALTER TABLE ingestion_jobs DROP CONSTRAINT IF EXISTS ingestion_jobs_status_check"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_status_check "
        "CHECK (status IN ('pending','running','completed','failed','dead','canceled','partial'))"
    )

    # ------------------------------------------------------------ permisos
    op.execute(
        """
        INSERT INTO permissions (id, code, description) VALUES
            ('40000000-0000-0000-0000-000000000051', 'catalog:read',
             'Ver catálogo semántico y descubrimiento'),
            ('40000000-0000-0000-0000-000000000052', 'catalog:write',
             'Gestionar catálogo, glosario, métricas y revisar sugerencias')
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'owner' "
        "AND p.code IN ('catalog:read','catalog:write') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'admin' "
        "AND p.code IN ('catalog:read','catalog:write') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'member' "
        "AND p.code IN ('catalog:read','catalog:write') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.organization_id IS NULL AND r.name = 'viewer' "
        "AND p.code IN ('catalog:read') ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in (
        "catalog_lineage",
        "catalog_enum_values",
        "catalog_suggestions",
        "catalog_authority",
        "catalog_metrics",
        "catalog_fields",
        "catalog_entities",
        "catalog_relationships",
        "catalog_columns",
        "catalog_tables",
        "catalog_scans",
        "catalog_sources",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(
        "ALTER TABLE business_definitions "
        "DROP COLUMN IF EXISTS synonyms, DROP COLUMN IF EXISTS owner, "
        "DROP COLUMN IF EXISTS version, DROP COLUMN IF EXISTS effective_from, "
        "DROP COLUMN IF EXISTS effective_to, DROP COLUMN IF EXISTS approved_by, "
        "DROP COLUMN IF EXISTS provenance"
    )
    op.execute(
        "ALTER TABLE context_gaps DROP CONSTRAINT IF EXISTS context_gaps_gap_type_check"
    )
    op.execute(
        "ALTER TABLE context_gaps ADD CONSTRAINT context_gaps_gap_type_check "
        "CHECK (gap_type IN ('CONTEXT_MISSING','DATA_MISSING'))"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs DROP CONSTRAINT IF EXISTS ingestion_jobs_status_check"
    )
    op.execute(
        "ALTER TABLE ingestion_jobs ADD CONSTRAINT ingestion_jobs_status_check "
        "CHECK (status IN ('pending','running','completed','failed','dead','canceled'))"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('catalog:read','catalog:write')"
    )

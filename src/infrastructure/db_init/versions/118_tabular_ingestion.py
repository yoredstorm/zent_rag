"""Knowledge Tabular V2 — structured representation (Excel/CSV).

Crea tabular_workbooks / tabular_sheets / tabular_tables / tabular_columns /
tabular_rows / tabular_relations: la representación ESTRUCTURADA (relacional)
de Excel/CSV, complementaria a la representación semántica en Qdrant.

Aislamiento idéntico al resto de la plataforma: organization_id obligatorio en
todas las tablas y en todas las queries; source_id/workspace_id opcionales para
filtrado. Las filas guardan `values` (normalized_name → raw exacto) y `cells`
JSONB con formulas/merged/posiciones físicas — la provenance llega a celda.

Revision ID: 118
Revises: 117
"""
from __future__ import annotations

from alembic import op

revision: str = "118"
down_revision: str = "117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_workbooks (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            workspace_id UUID,
            source_id UUID,
            knowledge_base_id UUID,
            external_id VARCHAR(512) NOT NULL,
            filename TEXT NOT NULL DEFAULT '',
            format VARCHAR(16) NOT NULL DEFAULT 'xlsx',
            content_hash VARCHAR(64) NOT NULL DEFAULT '',
            sheet_count INTEGER NOT NULL DEFAULT 0,
            table_count INTEGER NOT NULL DEFAULT 0,
            row_count BIGINT NOT NULL DEFAULT 0,
            cell_count BIGINT NOT NULL DEFAULT 0,
            profile JSONB NOT NULL DEFAULT '{}'::jsonb,
            quality JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (organization_id, source_id, external_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_workbooks_org_source "
        "ON tabular_workbooks(organization_id, source_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_sheets (
            id UUID PRIMARY KEY,
            workbook_id UUID NOT NULL
                REFERENCES tabular_workbooks(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            sheet_index INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT '',
            hidden BOOLEAN NOT NULL DEFAULT false,
            state VARCHAR(16) NOT NULL DEFAULT 'visible',
            dimensions JSONB,
            non_empty_cells BIGINT NOT NULL DEFAULT 0,
            merged_ranges INTEGER NOT NULL DEFAULT 0,
            context JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (workbook_id, sheet_index)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_sheets_org_workbook "
        "ON tabular_sheets(organization_id, workbook_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_tables (
            id UUID PRIMARY KEY,
            workbook_id UUID NOT NULL
                REFERENCES tabular_workbooks(id) ON DELETE CASCADE,
            sheet_id UUID NOT NULL
                REFERENCES tabular_sheets(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id UUID,
            name TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            table_range JSONB NOT NULL DEFAULT '{}'::jsonb,
            header_rows JSONB NOT NULL DEFAULT '[]'::jsonb,
            header_depth INTEGER NOT NULL DEFAULT 1,
            detection_method VARCHAR(32) NOT NULL DEFAULT 'heuristic',
            detection_confidence REAL NOT NULL DEFAULT 0,
            header_confidence REAL NOT NULL DEFAULT 0,
            schema_hash VARCHAR(64) NOT NULL DEFAULT '',
            content_hash VARCHAR(64) NOT NULL DEFAULT '',
            column_count INTEGER NOT NULL DEFAULT 0,
            row_count INTEGER NOT NULL DEFAULT 0,
            context JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_tables_org_source "
        "ON tabular_tables(organization_id, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_tables_sheet "
        "ON tabular_tables(sheet_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_tables_org_name "
        "ON tabular_tables(organization_id, name)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_columns (
            id UUID PRIMARY KEY,
            table_id UUID NOT NULL REFERENCES tabular_tables(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            physical_index INTEGER NOT NULL DEFAULT 0,
            physical_column INTEGER NOT NULL DEFAULT 1,
            excel_letter VARCHAR(8) NOT NULL DEFAULT 'A',
            original_name TEXT NOT NULL DEFAULT '',
            normalized_name TEXT NOT NULL DEFAULT '',
            aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
            header_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            inferred_type VARCHAR(24) NOT NULL DEFAULT 'unknown',
            semantic_type VARCHAR(24) NOT NULL DEFAULT 'unknown',
            type_confidence REAL NOT NULL DEFAULT 0,
            semantic_confidence REAL NOT NULL DEFAULT 0,
            nullable BOOLEAN NOT NULL DEFAULT true,
            null_ratio REAL NOT NULL DEFAULT 0,
            unique_ratio REAL NOT NULL DEFAULT 0,
            sample_values JSONB NOT NULL DEFAULT '[]'::jsonb,
            description TEXT NOT NULL DEFAULT '',
            description_origin VARCHAR(16) NOT NULL DEFAULT 'DETERMINISTIC',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (table_id, physical_column)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_columns_table "
        "ON tabular_columns(table_id, physical_index)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_columns_org_name "
        "ON tabular_columns(organization_id, normalized_name)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_rows (
            table_id UUID NOT NULL REFERENCES tabular_tables(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            physical_row INTEGER NOT NULL,
            logical_index INTEGER NOT NULL DEFAULT 0,
            values JSONB NOT NULL DEFAULT '{}'::jsonb,
            cells JSONB NOT NULL DEFAULT '[]'::jsonb,
            content_hash VARCHAR(64) NOT NULL DEFAULT '',
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (table_id, physical_row)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_rows_org "
        "ON tabular_rows(organization_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_rows_values "
        "ON tabular_rows USING GIN (values jsonb_path_ops)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tabular_relations (
            id UUID PRIMARY KEY,
            workbook_id UUID NOT NULL
                REFERENCES tabular_workbooks(id) ON DELETE CASCADE,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            from_table_id UUID NOT NULL,
            from_column_id UUID NOT NULL,
            to_table_id UUID NOT NULL,
            to_column_id UUID NOT NULL,
            kind VARCHAR(24) NOT NULL DEFAULT 'candidate_join',
            confidence REAL NOT NULL DEFAULT 0,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tabular_relations_workbook "
        "ON tabular_relations(organization_id, workbook_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tabular_relations")
    op.execute("DROP TABLE IF EXISTS tabular_rows")
    op.execute("DROP TABLE IF EXISTS tabular_columns")
    op.execute("DROP TABLE IF EXISTS tabular_tables")
    op.execute("DROP TABLE IF EXISTS tabular_sheets")
    op.execute("DROP TABLE IF EXISTS tabular_workbooks")

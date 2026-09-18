# =============================================================================
# Knowledge V2 — CSV parser (Knowledge Tabular V2)
# =============================================================================
# CSV pasa por el MISMO pipeline tabular que Excel (profiling, schema, tipos,
# jerarquía, persistencia estructurada). Workbook = un sheet = una tabla.
# Detecta encoding, BOM, delimitador, quotechar y estilo decimal.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
)
from src.knowledge.tabular.builder import build_tabular_workbook
from src.knowledge.tabular.csv_reader import CsvReadError, build_csv_workbook_grid
from src.knowledge.tabular.document import document_id_for, tabular_document
from src.knowledge.tabular.limits import tabular_limits

_NS = UUID("3f6b8d20-9a1c-4e57-8b3d-5c2f0a7e4d10")


class CsvParser(StructuredParser):
    """csv/tsv → StructuredDocument con árbol TabularWorkbook completo."""

    kind = "csv"
    mime_type = "text/csv"

    def parse(
        self,
        data: bytes,
        *,
        organization_id: UUID,
        external_id: str,
        source_id: UUID | None = None,
        workspace_id: UUID | None = None,
        source_name: str = "document",
        mime_type: str | None = None,
    ) -> StructuredDocument:
        limits = tabular_limits()
        try:
            grid, _dialect = build_csv_workbook_grid(
                data,
                source_name,
                max_rows=limits.max_rows_per_sheet,
                max_columns=limits.max_columns,
                max_cells=limits.max_cells,
            )
        except CsvReadError as exc:
            raise StructuredParserError(str(exc)) from exc

        workbook = build_tabular_workbook(
            grid,
            organization_id=organization_id,
            external_id=external_id,
            source_id=source_id,
            workspace_id=workspace_id,
            limits=limits,
            filename=source_name,
        )
        document_id = document_id_for(_NS, organization_id, source_id, external_id)
        return tabular_document(
            workbook,
            document_id=document_id,
            title=workbook.filename,
            mime_type=mime_type or self.mime_type,
            metadata={"limits_hit": list(grid.limits_hit)},
        )

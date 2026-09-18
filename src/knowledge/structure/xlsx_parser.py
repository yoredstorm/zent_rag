# =============================================================================
# Knowledge V2 — XLSX parser (Knowledge Tabular V2)
# =============================================================================
# Excel ciudadano de primera clase: workbook → sheets → tablas → columnas/filas
# con posiciones físicas, tipos, merged cells, formulas (sin evaluar) y
# provenance. El StructuredDocument resultante conserva el esqueleto; el árbol
# tabular completo viaja en `document.tabular`.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.knowledge_v2 import StructuredDocument
from src.knowledge.structure.base import (
    StructuredParser,
    StructuredParserError,
)
from src.knowledge.tabular.builder import build_tabular_workbook
from src.knowledge.tabular.document import document_id_for, tabular_document
from src.knowledge.tabular.limits import tabular_limits
from src.knowledge.tabular.xlsx_reader import XlsxReadError, read_xlsx_grid

_NS = UUID("7c9e2a41-5d8b-4f3a-b6e2-1a4c7d9f2b60")


class XlsxParser(StructuredParser):
    """xlsx/xlsm → StructuredDocument con árbol TabularWorkbook completo."""

    kind = "xlsx"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
            grid = read_xlsx_grid(
                data,
                source_name,
                max_sheets=limits.max_sheets,
                max_rows_per_sheet=limits.max_rows_per_sheet,
                max_columns=limits.max_columns,
                max_cells=limits.max_cells,
            )
        except XlsxReadError as exc:
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

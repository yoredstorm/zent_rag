# =============================================================================
# Semantic Reconstruction Layer — Spreadsheet / CSV Source Adapters
# =============================================================================
# Regla de oro del contrato: una tabla NO es texto. El adapter conserva
# workbook -> sheet -> table -> header/column/row/range, tipos, formulas,
# celdas fusionadas y contexto. El Knowledge Compiler recibe estructura, no
# miles de frases aplanadas.
# =============================================================================
from __future__ import annotations

from src.core.domain.knowledge_v2 import StructuredDocument
from src.core.domain.tabular import (
    TabularContextBlock,
    TabularContextKind,
    TabularTable,
    TabularWorkbook,
)

from ..contracts import (
    ElementKind,
    RawElement,
    RawExtraction,
    RawTable,
    SourceKind,
    SourceProvenance,
    element_uuid,
)
from .base import SourceAdapter


def _cell_details(row) -> tuple[list[dict], list[dict]]:
    merged: list[dict] = []
    formulas: list[dict] = []
    for detail in getattr(row, "cell_details", ()) or ():
        if getattr(detail, "is_merged", False):
            merged.append(
                {
                    "address": detail.address,
                    "physical_row": detail.physical_row,
                    "physical_column": detail.physical_column,
                    "range": _range_label(detail.merged_range),
                    "value": (detail.raw_value or "")[:200],
                }
            )
        if getattr(detail, "formula", None):
            formulas.append(
                {
                    "address": detail.address,
                    "formula": str(detail.formula)[:300],
                    "cached_value": str(detail.formula_cached_value or "")[:200],
                }
            )
    return merged, formulas


def _range_label(cell_range) -> str | None:
    if cell_range is None:
        return None
    try:
        from src.core.domain.tabular import cell_address

        return (
            f"{cell_address(cell_range.min_row, cell_range.min_col)}:"
            f"{cell_address(cell_range.max_row, cell_range.max_col)}"
        )
    except Exception:  # noqa: BLE001 — un label es metadata, no crítico
        return None


def _context_kind(block: TabularContextBlock) -> str:
    return {
        TabularContextKind.TITLE.value: ElementKind.TITLE.value,
        TabularContextKind.SUBTITLE.value: ElementKind.HEADING.value,
        TabularContextKind.NOTE.value: ElementKind.NOTE.value,
        TabularContextKind.FOOTER.value: ElementKind.FOOTER.value,
        TabularContextKind.HEADER_NOTE.value: ElementKind.NOTE.value,
    }.get(block.kind.value if hasattr(block.kind, "value") else str(block.kind), ElementKind.NOTE.value)


class _SpreadsheetAdapterBase(SourceAdapter):
    kind = SourceKind.SPREADSHEET.value
    description = "Excel/CSV: estructura tabular completa, nunca filas a texto"

    def extract(
        self,
        document: StructuredDocument,
        *,
        raw_text: str | None = None,
    ) -> RawExtraction:
        workbook: TabularWorkbook | None = document.tabular
        extraction = RawExtraction(
            source_kind=self.kind,
            adapter=self.name,
            title=document.title or document.external_id,
        )
        if workbook is None:
            extraction.warnings.append("document has no tabular workbook")
            return extraction

        relations_by_table: dict[str, list[dict]] = {}
        for relation in getattr(workbook, "relations", ()) or ():
            relation_kind = getattr(relation, "kind", "")
            payload = {
                "kind": getattr(relation_kind, "value", str(relation_kind)),
                "confidence": float(getattr(relation, "confidence", 0.0) or 0.0),
                "from_table_id": str(getattr(relation, "from_table_id", "")),
                "to_table_id": str(getattr(relation, "to_table_id", "")),
                "from_column_id": str(getattr(relation, "from_column_id", "")),
                "to_column_id": str(getattr(relation, "to_column_id", "")),
                "evidence": dict(getattr(relation, "evidence", {}) or {}),
            }
            for table_id in (payload["from_table_id"], payload["to_table_id"]):
                if table_id:
                    relations_by_table.setdefault(table_id, []).append(payload)

        position = 0

        def add(element: RawElement) -> None:
            nonlocal position
            position += 1
            extraction.elements.append(element)

        add(
            RawElement(
                id=element_uuid(document.id, position, workbook.filename),
                kind=ElementKind.WORKBOOK.value,
                text=workbook.filename,
                order=0,
                depth=0,
                provenance=SourceProvenance(
                    source_kind=self.kind,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    content_hash=workbook.content_hash,
                    excerpt=workbook.filename,
                ),
                confidence=0.95,
                attributes={"format": workbook.format.value, "sheets": workbook.sheet_count},
            )
        )

        for sheet in workbook.sheets:
            add(
                RawElement(
                    id=element_uuid(document.id, position, sheet.name),
                    kind=ElementKind.SHEET.value,
                    text=sheet.name,
                    order=position,
                    depth=1,
                    provenance=SourceProvenance(
                        source_kind=self.kind,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        sheet=sheet.name,
                        excerpt=sheet.name,
                    ),
                    confidence=1.0,
                    attributes={
                        "index": sheet.index,
                        "hidden": bool(sheet.hidden),
                        "state": sheet.state,
                        "table_count": sheet.table_count,
                        "merged_ranges": len(sheet.merged_ranges or ()),
                        "dimensions": _range_label(sheet.dimensions),
                    },
                )
            )
            for context in sheet.context_blocks or ():
                add(
                    RawElement(
                        id=element_uuid(document.id, position, context.text),
                        kind=_context_kind(context),
                        text=context.text,
                        order=position,
                        depth=2,
                        provenance=SourceProvenance(
                            source_kind=self.kind,
                            adapter=self.name,
                            source_id=document.source_id,
                            document_id=document.id,
                            document_title=document.title,
                            sheet=sheet.name,
                            row=context.physical_row,
                            column=None,
                            cell=(
                                f"R{context.physical_row}C{context.physical_column}"
                                if context.physical_row and context.physical_column
                                else None
                            ),
                            excerpt=context.text[:400],
                        ),
                        confidence=float(context.confidence or 0.6),
                    )
                )
            for table in sheet.tables:
                self._extract_table(
                    document,
                    extraction,
                    workbook,
                    sheet=sheet,
                    table=table,
                    add=add,
                    relations=relations_by_table.get(str(table.id), ()),
                )

        extraction.stats = {
            "sheets": workbook.sheet_count,
            "tables": workbook.table_count,
            "rows": workbook.row_count,
            "columns": sum(table.column_count for table in workbook.tables()),
            "elements": len(extraction.elements),
        }
        return extraction

    def _extract_table(
        self,
        document: StructuredDocument,
        extraction: RawExtraction,
        workbook: TabularWorkbook,
        *,
        sheet,
        table: TabularTable,
        add,
        relations: tuple | list = (),
    ) -> None:
        reference = f"{sheet.name}!{table.name}"
        range_label = _range_label(table.range)
        merged_cells: list[dict] = []
        formulas: list[dict] = []
        rows: list[tuple[str, ...]] = []
        for row in table.rows:
            rows.append(tuple(row.values))
            row_merged, row_formulas = _cell_details(row)
            merged_cells.extend(row_merged)
            formulas.extend(row_formulas)

        headers = tuple(column.original_name or column.normalized_name for column in table.columns)
        table_element_id = element_uuid(document.id, len(extraction.elements), reference)
        extraction.tables.append(
            RawTable(
                id=str(table.id),
                name=reference,
                headers=headers,
                rows=tuple(rows),
                header_depth=int(table.header_depth or 1),
                merged_cells=tuple(merged_cells),
                formulas=tuple(formulas),
                title=table.title or reference,
                provenance=SourceProvenance(
                    source_kind=self.kind,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    sheet=sheet.name,
                    table=reference,
                    cell=range_label,
                    content_hash=table.content_hash,
                    excerpt=f"Tabla {reference}",
                ),
                confidence=float(table.detection_confidence or 0.8),
                metadata={
                    "sheet": sheet.name,
                    "range": range_label,
                    "header_rows": list(table.header_rows or ()),
                    "detection_method": (
                        table.detection_method.value
                        if hasattr(table.detection_method, "value")
                        else str(table.detection_method)
                    ),
                    "header_confidence": float(table.header_confidence or 0.0),
                    "candidate_relations": [dict(item) for item in relations][:50],
                },
            )
        )
        add(
            RawElement(
                id=table_element_id,
                kind=ElementKind.TABLE.value,
                text=reference,
                order=len(extraction.elements),
                depth=2,
                provenance=SourceProvenance(
                    source_kind=self.kind,
                    adapter=self.name,
                    source_id=document.source_id,
                    document_id=document.id,
                    document_title=document.title,
                    sheet=sheet.name,
                    table=reference,
                    cell=range_label,
                    excerpt=f"Tabla {reference}",
                ),
                confidence=float(table.detection_confidence or 0.8),
                attributes={
                    "row_count": len(rows),
                    "column_count": len(headers),
                    "header_depth": int(table.header_depth or 1),
                    "range": range_label,
                    "merged_cells": len(merged_cells),
                    "formulas": len(formulas),
                },
            )
        )
        for column in table.columns:
            name = column.original_name or column.normalized_name
            add(
                RawElement(
                    id=element_uuid(document.id, len(extraction.elements), f"{reference}:{name}"),
                    kind=ElementKind.FIELD.value,
                    text=name,
                    order=len(extraction.elements),
                    depth=3,
                    parent_id=table_element_id,
                    provenance=SourceProvenance(
                        source_kind=self.kind,
                        adapter=self.name,
                        source_id=document.source_id,
                        document_id=document.id,
                        document_title=document.title,
                        sheet=sheet.name,
                        table=reference,
                        column=name,
                        cell=f"{column.excel_letter}1",
                        excerpt=column.description or name,
                    ),
                    confidence=float(column.semantic_confidence or 0.8),
                    attributes={
                        "physical_index": column.physical_index,
                        "physical_column": column.physical_column,
                        "excel_letter": column.excel_letter,
                        "normalized_name": column.normalized_name,
                        "inferred_type": column.inferred_type.value,
                        "semantic_type": column.semantic_type.value,
                        "type_confidence": float(column.type_confidence or 0.0),
                        "nullable": bool(column.nullable),
                        "null_ratio": float(column.null_ratio or 0.0),
                        "unique_ratio": float(column.unique_ratio or 0.0),
                        "header_path": list(column.header_path or ()),
                        "aliases": list(column.aliases or ()),
                        "sample_values": list(column.sample_values or ())[:5],
                        "description": column.description,
                        "table_id": str(table.id),
                    },
                )
            )


class SpreadsheetSourceAdapter(_SpreadsheetAdapterBase):
    kind = SourceKind.SPREADSHEET.value
    description = "Excel: workbook/sheet/table/column/row/merged/formula"


class CsvSourceAdapter(_SpreadsheetAdapterBase):
    kind = SourceKind.CSV.value
    description = "CSV/TSV: una tabla con headers, tipos y filas exactas"


__all__ = ["CsvSourceAdapter", "SpreadsheetSourceAdapter"]

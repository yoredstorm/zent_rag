# =============================================================================
# Tabular ingestion — TabularWorkbook → StructuredDocument (esqueleto V2)
# =============================================================================
# El StructuredDocument de un Excel/CSV conserva SOLO el esqueleto (hojas,
# contexto, schema de tablas). Las filas viven en el árbol `tabular` y en las
# tablas relacionales; así structured_blocks no duplica 100k filas.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4, uuid5

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    DocumentSection,
    DocumentTable,
    KnowledgeObjectStatus,
    StructuredBlock,
    StructuredBlockKind,
    StructuredContentType,
    StructuredDocument,
)
from src.core.domain.tabular import TabularWorkbook
from src.knowledge.structure.base import content_hash, token_count

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def tabular_document(
    workbook: TabularWorkbook,
    *,
    document_id: UUID,
    title: str | None = None,
    mime_type: str | None = None,
    metadata: dict | None = None,
) -> StructuredDocument:
    """Construye el StructuredDocument esqueleto del workbook tabular."""
    blocks: list[StructuredBlock] = []
    sections: list[DocumentSection] = []
    tables: list[DocumentTable] = []
    order = 0
    namespace = UUID("e5b7c2a1-6d4f-4a8b-9c3e-7f1d2a6b8c50")  # TABULAR_NS

    def node(kind: str, base: UUID) -> UUID:
        return uuid5(namespace, f"structured:{kind}:{base}")

    def emit(
        kind: StructuredBlockKind,
        text: str,
        page: int | None = None,
        *,
        block_id: UUID | None = None,
    ) -> StructuredBlock:
        nonlocal order
        block = StructuredBlock(
            kind=kind,
            text=text,
            order=order,
            page=page,
            content_type=(
                StructuredContentType.TABLE if kind is StructuredBlockKind.TABLE else StructuredContentType.TEXT
            ),
            token_count=token_count(text),
            content_hash=content_hash(text),
            id=block_id or uuid4(),
        )
        order += 1
        blocks.append(block)
        return block

    for sheet in workbook.sheets:
        sheet_identifier = sheet.id
        heading_text = sheet.name + (" (hidden)" if sheet.hidden else "")
        heading = emit(
            StructuredBlockKind.HEADING,
            heading_text,
            page=sheet.index + 1,
            block_id=node("heading", sheet.id),
        )
        sheet_section = DocumentSection(
            id=sheet_identifier,
            document_id=document_id,
            organization_id=workbook.organization_id,
            workspace_id=workbook.workspace_id,
            source_id=workbook.source_id,
            section_path=(sheet.name,),
            heading=sheet.name,
            depth=0,
            order=heading.order,
            block_ids=(heading.id,),
            text=heading_text,
            token_count=token_count(heading_text),
            content_hash=content_hash(heading_text),
            metadata={"knowledge_type": "table_sheet", "sheet_id": str(sheet.id)},
        )
        sections.append(sheet_section)

        for context_index, block in enumerate(sheet.context_blocks[:10]):
            emit(
                StructuredBlockKind.PARAGRAPH,
                block.text,
                page=sheet.index + 1,
                block_id=node("context", uuid5(namespace, f"sheet:{sheet.id}:{context_index}")),
            )

        for table in sheet.tables:
            schema_text = _render_schema(sheet.name, workbook, table)
            table_block = emit(
                StructuredBlockKind.TABLE,
                schema_text,
                page=sheet.index + 1,
                block_id=node("table_block", table.id),
            )
            table_section = DocumentSection(
                id=node("table_section", table.id),
                document_id=document_id,
                organization_id=workbook.organization_id,
                workspace_id=workbook.workspace_id,
                source_id=workbook.source_id,
                section_path=(sheet.name, table.name),
                heading=table.name,
                depth=1,
                parent_id=sheet_identifier,
                order=table_block.order,
                block_ids=(table_block.id,),
                text=schema_text,
                token_count=token_count(schema_text),
                content_hash=content_hash(schema_text),
                metadata={
                    "knowledge_type": "table_schema",
                    "table_id": str(table.id),
                    "sheet_id": str(sheet.id),
                },
            )
            sections.append(table_section)
            tables.append(
                DocumentTable(
                    id=node("doc_table", table.id),
                    document_id=document_id,
                    organization_id=workbook.organization_id,
                    workspace_id=workbook.workspace_id,
                    source_id=workbook.source_id,
                    caption=table.name,
                    headers=table.column_names,
                    rows=(),
                    token_count=token_count(schema_text),
                    content_hash=table.schema_hash,
                    metadata={
                        "knowledge_type": "table_schema",
                        "sheet": sheet.name,
                        "table_id": str(table.id),
                        "row_count": table.row_count,
                        "range": table.range.to_dict(),
                        "header_rows": list(table.header_rows),
                        "columns": [
                            {
                                "original_name": column.original_name,
                                "normalized_name": column.normalized_name,
                                "excel_letter": column.excel_letter,
                                "physical_column": column.physical_column,
                                "inferred_type": column.inferred_type.value,
                                "semantic_type": column.semantic_type.value,
                                "aliases": list(column.aliases),
                                "confidence": column.type_confidence,
                            }
                            for column in table.columns
                        ],
                    },
                )
            )

    content_hash_value = workbook.content_hash or content_hash(
        "\n".join(block.text for block in blocks)
    )
    document_metadata = {
        "tabular": True,
        "format": workbook.format.value,
        "workbook_id": str(workbook.id),
        "sheet_count": workbook.sheet_count,
        "table_count": workbook.table_count,
        "row_count": workbook.row_count,
        "quality_score": workbook.quality.quality_score if workbook.quality else None,
        **(workbook.metadata or {}),
        **(metadata or {}),
    }
    return StructuredDocument(
        id=document_id,
        organization_id=workbook.organization_id,
        workspace_id=workbook.workspace_id,
        source_id=workbook.source_id,
        external_id=workbook.external_id,
        title=title or workbook.filename,
        content_hash=content_hash_value,
        mime_type=mime_type or _mime_for(workbook),
        document_type="spreadsheet",
        language=workbook.language,
        blocks=tuple(blocks),
        pages=(),
        sections=tuple(sections),
        tables=tuple(tables),
        figures=(),
        tabular=workbook,
        provenance=CatalogProvenance.OBSERVED,
        status=KnowledgeObjectStatus.OBSERVED,
        metadata=document_metadata,
    )


def _render_schema(sheet_name: str, workbook: TabularWorkbook, table) -> str:
    lines = [
        f"TABLE: {table.name}",
        f"Sheet: {sheet_name}",
        f"Workbook: {workbook.filename}",
    ]
    if table.title:
        lines.append(f"Title: {table.title}")
    lines.append("COLUMNS:")
    for column in table.columns:
        lines.append(
            f"- {column.original_name or column.normalized_name} "
            f"[{column.excel_letter}] ({column.semantic_type.value}, "
            f"{column.inferred_type.value})"
        )
    lines.append(f"Rows: {table.row_count}")
    return "\n".join(lines)


def _mime_for(workbook: TabularWorkbook) -> str:
    if workbook.format.value in ("csv", "tsv"):
        return "text/csv"
    return _XLSX_MIME


def document_id_for(
    namespace: UUID, organization_id: UUID, source_id: UUID | None, external_id: str
) -> UUID:
    return uuid5(namespace, f"v2:{organization_id}:{source_id}:{external_id}")

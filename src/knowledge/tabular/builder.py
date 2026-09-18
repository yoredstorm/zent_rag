# =============================================================================
# Tabular ingestion — construcción del TabularWorkbook canónico
# =============================================================================
# Orquesta: detector (regiones/headers) → schema (tipos/semántica) → filas con
# hashes → calidad → relaciones candidatas. Puro y determinista (sin LLM).
# =============================================================================
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from uuid import UUID

from src.core.domain.tabular import (
    CellRange,
    TabularColumn,
    TabularContextBlock,
    TabularFormat,
    TabularRow,
    TabularSemanticType,
    TabularSheet,
    TabularTable,
    TabularValueType,
    TabularWorkbook,
    TabularWorkbookProfile,
)
from src.knowledge.tabular.detector import DetectedTable, detect_sheet_tables
from src.knowledge.tabular.grid import SheetGrid, WorkbookGrid
from src.knowledge.tabular.ids import (
    column_id as make_column_id,
)
from src.knowledge.tabular.ids import (
    sheet_id as make_sheet_id,
)
from src.knowledge.tabular.ids import (
    table_id as make_table_id,
)
from src.knowledge.tabular.ids import (
    workbook_id as make_workbook_id,
)
from src.knowledge.tabular.profiler import build_workbook_profile
from src.knowledge.tabular.quality import build_quality_report
from src.knowledge.tabular.relations import discover_relations
from src.knowledge.tabular.schema import (
    classify_value,
    header_aliases,
    infer_semantic_type,
    normalize_name,
    profile_values,
)
from src.knowledge.tabular.version import TABULAR_PIPELINE_VERSION

_ROW_SEPARATOR = "\x1f"


@dataclass(frozen=True, kw_only=True)
class TabularBuildLimits:
    max_sheets: int = 50
    max_rows_per_sheet: int = 100_000
    max_columns: int = 512
    max_cells: int = 2_000_000
    max_embedding_rows: int = 5_000
    max_header_rows: int = 4
    row_group_size: int = 40
    row_group_overlap: int = 2
    sample_values_per_column: int = 8


def build_tabular_workbook(
    workbook_grid: WorkbookGrid,
    *,
    organization_id: UUID,
    external_id: str,
    source_id: UUID | None = None,
    workspace_id: UUID | None = None,
    limits: TabularBuildLimits | None = None,
    filename: str | None = None,
) -> TabularWorkbook:
    """WorkbookGrid → TabularWorkbook (estructura completa + calidad)."""
    limits = limits or TabularBuildLimits()
    workbook_identifier = make_workbook_id(organization_id, source_id, external_id)
    sheets: list[TabularSheet] = []
    for grid in workbook_grid.sheets:
        sheets.append(_build_sheet(grid, workbook_identifier))
    workbook = TabularWorkbook(
        id=workbook_identifier,
        organization_id=organization_id,
        external_id=external_id,
        filename=filename or workbook_grid.filename,
        format=TabularFormat(workbook_grid.format),
        content_hash=workbook_grid.content_hash,
        sheets=tuple(sheets),
        workspace_id=workspace_id,
        source_id=source_id,
        metadata={
            "tabular_version": "v1",
            "pipeline_version": TABULAR_PIPELINE_VERSION,
            "sheet_count": len(sheets),
            "max_embedding_rows": limits.max_embedding_rows,
            "row_group_size": limits.row_group_size,
            "row_group_overlap": limits.row_group_overlap,
            **workbook_grid.metadata,
        },
    )
    relations = discover_relations(workbook)
    workbook = replace(workbook, relations=relations)
    profile = build_workbook_profile(workbook, workbook_grid)
    workbook = replace(workbook, profile=profile)
    quality = build_quality_report(
        workbook, grids={grid.name: grid for grid in workbook_grid.sheets}
    )
    workbook = replace(workbook, quality=quality)
    return workbook


def rebuild_profile(workbook: TabularWorkbook, workbook_grid: WorkbookGrid) -> TabularWorkbookProfile:
    return build_workbook_profile(workbook, workbook_grid)


# ---------------------------------------------------------------------------
# Hoja
# ---------------------------------------------------------------------------


def _build_sheet(grid: SheetGrid, workbook_identifier: UUID) -> TabularSheet:
    identifier = make_sheet_id(workbook_identifier, grid.index, grid.name)
    detected = detect_sheet_tables(grid)
    used_names: dict[str, int] = {}
    tables: list[TabularTable] = []
    for index, table in enumerate(detected.tables):
        name = _unique_name(table.name, used_names)
        tables.append(_build_table(grid, table, workbook_identifier, identifier, index, name))
    context = tuple(
        block
        for block in detected.context
        if isinstance(block, TabularContextBlock)
    )
    return TabularSheet(
        id=identifier,
        workbook_id=workbook_identifier,
        name=grid.name,
        index=grid.index,
        tables=tuple(tables),
        context_blocks=context,
        dimensions=grid.used_range(),
        non_empty_cells=grid.non_empty_cells,
        merged_ranges=tuple(
            merge
            for merge in grid.merged
            if grid.used_range() is None or _overlaps(merge, grid.used_range())
        ),
        hidden=grid.hidden,
        state=grid.state,
        metadata={
            "excel_tables": [table.name for table in grid.excel_tables],
            "formulas": len(grid.formulas),
            "truncated": grid.truncated,
        },
    )


def _build_table(
    grid: SheetGrid,
    detected: DetectedTable,
    workbook_identifier: UUID,
    sheet_identifier: UUID,
    index: int,
    name: str,
) -> TabularTable:
    identifier = make_table_id(workbook_identifier, sheet_identifier, index, name)
    table_range = detected.table_range
    physical_columns = [
        table_range.min_col + offset for offset in range(len(detected.column_names))
    ]

    # Valores por columna (una lista por columna, alineada a data_rows).
    # Índice de filas una sola vez: evita lookups O(n) por celda en workbooks
    # grandes (6750x24 pasaba de 87s a segundos).
    values_by_row = dict(grid.rows)
    row_start = max(0, table_range.min_col - grid.min_col)
    row_end = max(0, table_range.max_col - grid.min_col + 1)

    def has_data(physical_row: int) -> bool:
        values = values_by_row.get(physical_row)
        if values is None:
            return False
        return any(value != "" for value in values[row_start:row_end])

    data_rows = [
        row_number
        for row_number in range(detected.data_start_row, table_range.max_row + 1)
        if has_data(row_number)
    ]

    raw_by_column: list[list[str]] = [[] for _ in physical_columns]
    for row_number in data_rows:
        values = values_by_row.get(row_number, ())
        for offset, physical_column in enumerate(physical_columns):
            index = physical_column - grid.min_col
            raw_by_column[offset].append(
                values[index] if 0 <= index < len(values) else ""
            )
    # Recorte de columnas totalmente vacías al final (headers vacíos + sin datos).
    while len(physical_columns) > 1 and not any(
        value.strip() for value in raw_by_column[-1]
    ) and not (detected.column_labels[-1] if detected.column_labels else ()):
        physical_columns.pop()
        raw_by_column.pop()

    columns: list[TabularColumn] = []
    used_normalized: dict[str, int] = {}
    for offset, physical_column in enumerate(physical_columns):
        labels = (
            detected.column_labels[offset]
            if offset < len(detected.column_labels)
            else ()
        )
        original_name = labels[-1].strip() if labels else ""
        base_normalized = normalize_name(original_name) or f"column_{offset + 1}"
        normalized = _unique_normalized(base_normalized, used_normalized)
        profile = profile_values(raw_by_column[offset])
        semantic_type, semantic_confidence, aliases = infer_semantic_type(
            original_name,
            value_type=profile.inferred_type,
            max_length=profile.max_length,
        )
        inferred_type = profile.inferred_type
        type_confidence = profile.type_confidence
        # Coherencia header/valores: una columna declarada como código con
        # valores únicos cortos es un CODE aunque el patrón sea ambiguo. El
        # valor exacto nunca se normaliza (solo se etiqueta el tipo).
        if (
            inferred_type in (TabularValueType.STRING, TabularValueType.UNKNOWN)
            and semantic_type
            in (
                TabularSemanticType.CODE,
                TabularSemanticType.IDENTIFIER,
                TabularSemanticType.REFERENCE,
            )
            and profile.unique_ratio >= 0.8
            and profile.non_empty >= 2
        ):
            inferred_type = TabularValueType.CODE
            type_confidence = max(type_confidence, semantic_confidence * 0.9)
        column_aliases = tuple(dict.fromkeys(aliases + header_aliases(original_name)))
        columns.append(
            TabularColumn(
                id=make_column_id(identifier, physical_column),
                physical_index=offset,
                physical_column=physical_column,
                excel_letter=_excel_letter(physical_column),
                original_name=original_name,
                normalized_name=normalized,
                aliases=column_aliases,
                header_path=tuple(labels),
                inferred_type=inferred_type,
                semantic_type=semantic_type,
                type_confidence=type_confidence,
                semantic_confidence=semantic_confidence,
                nullable=profile.null_ratio > 0,
                null_ratio=profile.null_ratio,
                unique_ratio=profile.unique_ratio,
                sample_values=tuple(profile.samples[:8]),
                description="",
                metadata={
                    "non_empty": profile.non_empty,
                    "distinct": profile.distinct,
                    "error_values": list(profile.error_values),
                    "malformed_dates": list(profile.malformed_dates),
                    "mixed_values": list(profile.mixed_values),
                    "synthetic_name": not bool(original_name),
                    "header_depth": len(labels),
                    "deduplicated_name": normalized != base_normalized,
                },
            )
        )

    rows: list[TabularRow] = []
    merged_index = _merged_index(grid)
    for logical_index, row_number in enumerate(data_rows):
        values = tuple(
            raw_by_column[offset][logical_index] for offset in range(len(columns))
        )
        details = _cell_details(grid, row_number, columns, values, merged_index)
        rows.append(
            TabularRow(
                physical_row=row_number,
                logical_index=logical_index,
                values=values,
                cell_details=details,
                content_hash=_row_hash(columns, values),
                metadata={},
            )
        )

    schema_hash = _schema_hash(columns)
    content_hash = _table_content_hash(columns, rows)
    hidden_rows = tuple(
        sorted(
            row.physical_row
            for row in rows
            if row.physical_row in grid.hidden_rows
        )
    )
    header_rows = detected.header_rows
    return TabularTable(
        id=identifier,
        workbook_id=workbook_identifier,
        sheet_id=sheet_identifier,
        name=name,
        range=table_range,
        columns=tuple(columns),
        rows=tuple(rows),
        title=detected.title,
        context_lines=tuple(block.text for block in detected.context),
        context_blocks=detected.context,
        header_rows=header_rows,
        header_depth=len(header_rows),
        detection_method=detected.detection_method,
        detection_confidence=detected.detection_confidence,
        header_confidence=detected.header_confidence,
        schema_hash=schema_hash,
        content_hash=content_hash,
        metadata={
            "detection": detected.metadata,
            "excel_table": detected.excel_table.name if detected.excel_table else None,
            "hidden_rows": hidden_rows,
            "physical_columns": [column.physical_column for column in columns],
            "column_letters": [column.excel_letter for column in columns],
            "header_rows": list(header_rows),
        },
    )


# ---------------------------------------------------------------------------
# Hashes / detalles
# ---------------------------------------------------------------------------


def _row_hash(columns: list[TabularColumn], values: tuple[str, ...]) -> str:
    payload = _ROW_SEPARATOR.join(
        f"{column.normalized_name}={value}" for column, value in zip(columns, values)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema_hash(columns: list[TabularColumn]) -> str:
    payload = _ROW_SEPARATOR.join(
        f"{column.physical_column}:{column.normalized_name}:{column.inferred_type.value}:"
        f"{column.semantic_type.value}"
        for column in columns
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _table_content_hash(columns: list[TabularColumn], rows: list[TabularRow]) -> str:
    digest = hashlib.sha256()
    digest.update(_schema_hash(columns).encode("utf-8"))
    for row in rows:
        digest.update(row.content_hash.encode("utf-8"))
    return digest.hexdigest()


def _cell_details(
    grid: SheetGrid,
    row_number: int,
    columns: list[TabularColumn],
    values: tuple[str, ...],
    merged_by_cell: dict[tuple[int, int], CellRange],
) -> tuple:
    details = []
    for column, value in zip(columns, values):
        formula = grid.formulas.get((row_number, column.physical_column))
        merged = merged_by_cell.get((row_number, column.physical_column))
        # Columnas de texto puro sin fórmula/merged: no aportan detalle de celda
        # (el valor exacto ya vive en TabularRow.values). Evita clasificar
        # cientos de miles de celdas en workbooks grandes.
        if (
            formula is None
            and merged is None
            and column.inferred_type
            in (TabularValueType.STRING, TabularValueType.UNKNOWN)
        ):
            continue
        value_type = classify_value(value) if value else TabularValueType.UNKNOWN
        is_odd_type = (
            value != ""
            and column.inferred_type is not TabularValueType.MIXED
            and value_type is not TabularValueType.UNKNOWN
            and value_type is not column.inferred_type
        )
        if formula is None and merged is None and not is_odd_type:
            continue
        from src.core.domain.tabular import TabularCell

        details.append(
            TabularCell(
                physical_row=row_number,
                physical_column=column.physical_column,
                raw_value=value,
                inferred_type=value_type,
                formula=formula,
                is_merged=merged is not None,
                merged_range=merged,
                metadata={"column": column.normalized_name},
            )
        )
    return tuple(details)


def _merged_index(grid: SheetGrid) -> dict[tuple[int, int], CellRange]:
    index: dict[tuple[int, int], CellRange] = {}
    for merge in grid.merged:
        for row_number in range(merge.min_row, merge.max_row + 1):
            for column in range(merge.min_col, merge.max_col + 1):
                index[(row_number, column)] = merge
    return index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unique_name(name: str, used: dict[str, int]) -> str:
    key = name.strip().lower() or "table"
    count = used.get(key, 0) + 1
    used[key] = count
    if count == 1:
        return name.strip() or "Table"
    return f"{name.strip() or 'Table'} ({count})"


def _unique_normalized(base: str, used: dict[str, int]) -> str:
    """Nombre normalizado único dentro de una tabla (headers duplicados reales).

    El RAW original nunca se toca; solo el índice interno (values/JSONB) evita
    colisiones entre columnas homónimas ("Data Row" dos veces).
    """
    count = used.get(base, 0) + 1
    used[base] = count
    return base if count == 1 else f"{base}_{count}"


def _excel_letter(physical_column: int) -> str:
    from src.core.domain.tabular import column_letter

    return column_letter(physical_column)


def _overlaps(left: CellRange, right: CellRange) -> bool:
    return not (
        left.max_row < right.min_row
        or left.min_row > right.max_row
        or left.max_col < right.min_col
        or left.min_col > right.max_col
    )

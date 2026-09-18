# =============================================================================
# Tabular ingestion — reporte de calidad (no bloquea la ingesta)
# =============================================================================
# Detecta problemas comunes (headers duplicados/vacíos, filas duplicadas,
# tipos mixtos, nulos extremos, fechas inválidas, errores de fórmula, datos
# ocultos, IDs duplicados, celdas combinadas rotas, metadata antes del header).
# =============================================================================
from __future__ import annotations

from src.core.domain.tabular import (
    TabularQualityReport,
    TabularQualitySeverity,
    TabularQualityWarning,
    TabularSheet,
    TabularTable,
    TabularValueType,
    TabularWorkbook,
)
from src.knowledge.tabular.grid import SheetGrid

_SEVERITY_WEIGHT = {
    TabularQualitySeverity.INFO: 0.01,
    TabularQualitySeverity.WARNING: 0.05,
    TabularQualitySeverity.ERROR: 0.15,
}


def build_quality_report(
    workbook: TabularWorkbook,
    *,
    grids: dict[str, SheetGrid] | None = None,
) -> TabularQualityReport:
    """Evalúa calidad de cada tabla/hoja y agrega score global."""
    warnings: list[TabularQualityWarning] = []
    grids = grids or {}

    for sheet in workbook.sheets:
        grid = grids.get(sheet.name)
        if sheet.hidden or sheet.state != "visible":
            warnings.append(
                TabularQualityWarning(
                    code="hidden_sheet",
                    message=f"Sheet '{sheet.name}' is {sheet.state}: data hidden from normal view",
                    severity=TabularQualitySeverity.INFO,
                    sheet_name=sheet.name,
                )
            )
        if len(sheet.tables) > 1:
            warnings.append(
                TabularQualityWarning(
                    code="multiple_tables_in_sheet",
                    message=(
                        f"Sheet '{sheet.name}' contains {len(sheet.tables)} candidate tables"
                    ),
                    severity=TabularQualitySeverity.INFO,
                    sheet_name=sheet.name,
                )
            )
        if grid is not None:
            _check_grid_warnings(warnings, grid, sheet)
        for table in sheet.tables:
            _check_table_warnings(warnings, table, sheet)

    score = 1.0
    for warning in warnings:
        score -= _SEVERITY_WEIGHT.get(warning.severity, 0.02)
    score = max(0.05, min(1.0, round(score, 3)))
    by_code: dict[str, int] = {}
    for warning in warnings:
        by_code[warning.code] = by_code.get(warning.code, 0) + 1
    return TabularQualityReport(
        quality_score=score,
        warnings=tuple(warnings),
        metrics={
            "warning_counts": by_code,
            "tables": workbook.table_count,
            "rows": workbook.row_count,
        },
    )


def _check_grid_warnings(
    warnings: list[TabularQualityWarning], grid: SheetGrid, sheet: TabularSheet
) -> None:
    if grid.metadata.get("ragged_rows"):
        warnings.append(
            TabularQualityWarning(
                code="inconsistent_row_length",
                message=(
                    f"Sheet '{grid.name}' has {grid.metadata['ragged_rows']} rows with "
                    "fewer columns than the widest row"
                ),
                severity=TabularQualitySeverity.WARNING,
                sheet_name=grid.name,
            )
        )
    for merged in grid.merged:
        if sheet.dimensions is not None and (
            merged.min_row < sheet.dimensions.min_row
            or merged.max_row > sheet.dimensions.max_row
        ):
            warnings.append(
                TabularQualityWarning(
                    code="broken_merged_region",
                    message=(
                        f"Merged range at row {merged.min_row} falls outside the used range"
                    ),
                    severity=TabularQualitySeverity.INFO,
                    sheet_name=grid.name,
                )
            )
            break
    if grid.truncated:
        warnings.append(
            TabularQualityWarning(
                code="ingestion_truncated",
                message=(
                    f"Sheet '{grid.name}' was truncated by limits: "
                    f"{', '.join(grid.limits_hit) or 'unknown'}"
                ),
                severity=TabularQualitySeverity.WARNING,
                sheet_name=grid.name,
            )
        )


def _check_table_warnings(
    warnings: list[TabularQualityWarning], table: TabularTable, sheet: TabularSheet
) -> None:
    seen_names: dict[str, int] = {}
    display_names: dict[str, str] = {}
    for column in table.columns:
        key = (column.original_name or column.normalized_name).strip().lower()
        seen_names[key] = seen_names.get(key, 0) + 1
        display_names.setdefault(key, column.original_name or column.normalized_name)
    duplicates = sorted(
        display_names[name] for name, count in seen_names.items() if count > 1
    )
    if duplicates:
        warnings.append(
            TabularQualityWarning(
                code="duplicate_headers",
                message=(
                    f"Table '{table.name}' has duplicate headers: {', '.join(duplicates[:5])} "
                    "(columnas renombradas internamente con sufijo _2, _3, ...; el valor raw se conserva)"
                ),
                severity=TabularQualitySeverity.WARNING,
                sheet_name=sheet.name,
                table_id=table.id,
            )
        )

    synthetic = [
        column
        for column in table.columns
        if column.metadata.get("synthetic_name") and not column.original_name
    ]
    if synthetic:
        warnings.append(
            TabularQualityWarning(
                code="empty_headers",
                message=(
                    f"Table '{table.name}' has {len(synthetic)} columns without a header"
                ),
                severity=TabularQualitySeverity.INFO,
                sheet_name=sheet.name,
                table_id=table.id,
            )
        )

    for column in table.columns:
        if column.metadata.get("error_values"):
            warnings.append(
                TabularQualityWarning(
                    code="formula_errors",
                    message=(
                        f"Column {column.original_name!r} contains error values: "
                        f"{', '.join(column.metadata['error_values'][:3])}"
                    ),
                    severity=TabularQualitySeverity.WARNING,
                    sheet_name=sheet.name,
                    table_id=table.id,
                    column_name=column.original_name,
                )
            )
        if column.metadata.get("malformed_dates"):
            warnings.append(
                TabularQualityWarning(
                    code="malformed_dates",
                    message=(
                        f"Column {column.original_name!r} contains "
                        f"{len(column.metadata['malformed_dates'])} non-date values"
                    ),
                    severity=TabularQualitySeverity.WARNING,
                    sheet_name=sheet.name,
                    table_id=table.id,
                    column_name=column.original_name,
                )
            )
        if (
            column.inferred_type is TabularValueType.MIXED
            or (
                column.type_confidence < 0.75
                and column.metadata.get("mixed_values")
            )
        ):
            warnings.append(
                TabularQualityWarning(
                    code="mixed_types",
                    message=(
                        f"Column {column.original_name!r} mixes value types "
                        f"(confidence {column.type_confidence:.2f})"
                    ),
                    severity=TabularQualitySeverity.WARNING,
                    sheet_name=sheet.name,
                    table_id=table.id,
                    column_name=column.original_name,
                )
            )
        if column.null_ratio > 0.9 and column.metadata.get("non_empty", 0) > 0:
            warnings.append(
                TabularQualityWarning(
                    code="extreme_null_ratio",
                    message=(
                        f"Column {column.original_name!r} is {column.null_ratio:.0%} empty"
                    ),
                    severity=TabularQualitySeverity.INFO,
                    sheet_name=sheet.name,
                    table_id=table.id,
                    column_name=column.original_name,
                )
            )
        if (
            column.semantic_type.value in ("identifier", "code")
            and column.null_ratio < 0.5
            and column.unique_ratio < 0.95
            and column.metadata.get("non_empty", 0) >= 3
        ):
            warnings.append(
                TabularQualityWarning(
                    code="duplicate_ids",
                    message=(
                        f"Identifier column {column.original_name!r} is not unique "
                        f"({column.unique_ratio:.0%} distinct)"
                    ),
                    severity=TabularQualitySeverity.INFO,
                    sheet_name=sheet.name,
                    table_id=table.id,
                    column_name=column.original_name,
                )
            )

    hashes: dict[str, int] = {}
    for row in table.rows:
        if row.content_hash:
            hashes[row.content_hash] = hashes.get(row.content_hash, 0) + 1
    duplicates_rows = sum(count - 1 for count in hashes.values() if count > 1)
    if duplicates_rows:
        warnings.append(
            TabularQualityWarning(
                code="duplicate_rows",
                message=f"Table '{table.name}' has {duplicates_rows} duplicated row(s)",
                severity=TabularQualitySeverity.INFO,
                sheet_name=sheet.name,
                table_id=table.id,
            )
        )

    hidden_rows_inside = [
        row.physical_row
        for row in table.rows
        if row.physical_row in _hidden_rows_for(table)
    ]
    if hidden_rows_inside:
        warnings.append(
            TabularQualityWarning(
                code="hidden_data",
                message=(
                    f"Table '{table.name}' includes {len(hidden_rows_inside)} hidden row(s)"
                ),
                severity=TabularQualitySeverity.INFO,
                sheet_name=sheet.name,
                table_id=table.id,
            )
        )

    context_rows = [
        block.physical_row
        for block in table.context_blocks
        if block.kind.value in ("title", "subtitle") and block.physical_row is not None
    ]
    if context_rows:
        first = min(context_rows)
        last = max(context_rows)
        warnings.append(
            TabularQualityWarning(
                code="metadata_before_header",
                message=(
                    f"Rows {first}-{last} appear to contain metadata before the header "
                    f"of table '{table.name}'"
                ),
                severity=TabularQualitySeverity.INFO,
                sheet_name=sheet.name,
                table_id=table.id,
            )
        )


def _hidden_rows_for(table: TabularTable) -> frozenset[int]:
    return frozenset(table.metadata.get("hidden_rows") or ())

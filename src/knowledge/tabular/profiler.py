# =============================================================================
# Tabular ingestion — profiling determinista (sin LLM, sin cargar todo 2 veces)
# =============================================================================
# Calcula el perfil del workbook (brief §2) a partir de los grids normalizados
# y de las tablas detectadas: dimensiones, merged, formulas, filas/columnas
# ocultas, separadores, headers candidatos y tipos.
# =============================================================================
from __future__ import annotations

from src.core.domain.tabular import (
    TabularFormat,
    TabularSheetProfile,
    TabularWorkbook,
    TabularWorkbookProfile,
)
from src.knowledge.tabular.grid import SheetGrid, WorkbookGrid


def build_workbook_profile(
    workbook: TabularWorkbook,
    workbook_grid: WorkbookGrid,
) -> TabularWorkbookProfile:
    grids = {grid.name: grid for grid in workbook_grid.sheets}
    sheets: list[TabularSheetProfile] = []
    for sheet in workbook.sheets:
        grid = grids.get(sheet.name)
        sheets.append(_sheet_profile(sheet, grid))
    limits_hit = list(dict.fromkeys(workbook_grid.limits_hit))
    return TabularWorkbookProfile(
        filename=workbook.filename,
        format=workbook.format,
        sheet_count=workbook.sheet_count,
        sheet_names=tuple(sheet.name for sheet in workbook.sheets),
        sheets=tuple(sheets),
        non_empty_cells=sum(profile.non_empty_cells for profile in sheets),
        merged_cells=sum(profile.merged_ranges for profile in sheets),
        formulas=sum(profile.formulas for profile in sheets),
        hidden_rows=sum(profile.hidden_rows for profile in sheets),
        hidden_columns=sum(profile.hidden_columns for profile in sheets),
        candidate_tables=sum(profile.candidate_tables for profile in sheets),
        truncated=workbook_grid.truncated
        or any(bool(sheet.metadata.get("truncated")) for sheet in workbook.sheets),
        limits_hit=tuple(limits_hit),
        metadata={
            "source_bytes": workbook_grid.source_bytes,
            "sheet_order": list(workbook_grid.sheet_names),
            **workbook_grid.metadata,
        },
    )


def _sheet_profile(sheet, grid: SheetGrid | None) -> TabularSheetProfile:
    if grid is None:
        return TabularSheetProfile(
            name=sheet.name,
            index=sheet.index,
            non_empty_cells=sheet.non_empty_cells,
            detected_tables=len(sheet.tables),
            candidate_tables=len(sheet.tables),
            hidden=sheet.hidden,
        )
    used = grid.used_range()
    formulas = len(grid.formulas) or int(grid.metadata.get("formula_count") or 0)
    return TabularSheetProfile(
        name=sheet.name,
        index=sheet.index,
        row_count=grid.non_empty_rows,
        column_count=used.column_count if used else 0,
        non_empty_cells=grid.non_empty_cells,
        used_range=used,
        merged_ranges=len(grid.merged),
        formulas=formulas,
        hidden_rows=len(grid.hidden_rows),
        hidden_columns=len(grid.hidden_columns),
        blank_row_separators=_blank_row_separators(grid),
        blank_column_separators=_blank_column_separators(grid, used),
        candidate_header_rows=tuple(
            sorted({row for table in sheet.tables for row in table.header_rows})
        ),
        candidate_tables=len(sheet.tables),
        detected_tables=len(sheet.tables),
        hidden=sheet.hidden,
        metadata={"sheet_state": sheet.state},
    )


def _blank_row_separators(grid: SheetGrid) -> tuple[int, ...]:
    non_empty = [row for row, values in grid.rows if any(v != "" for v in values)]
    if len(non_empty) < 2:
        return ()
    first, last = non_empty[0], non_empty[-1]
    present = set(non_empty)
    return tuple(row for row in range(first + 1, last) if row not in present)


def _blank_column_separators(grid: SheetGrid, used) -> tuple[int, ...]:
    if used is None:
        return ()
    columns_with_values: set[int] = set()
    for _row, values in grid.rows:
        for offset, value in enumerate(values):
            if value != "":
                columns_with_values.add(grid.min_col + offset)
    return tuple(
        column
        for column in range(used.min_col + 1, used.max_col)
        if column not in columns_with_values
    )


def infer_workbook_format(extension: str) -> TabularFormat:
    normalized = (extension or "").lower().lstrip(".")
    if normalized in ("xlsm",):
        return TabularFormat.XLSM
    if normalized in ("xls",):
        return TabularFormat.XLS
    if normalized in ("tsv",):
        return TabularFormat.TSV
    if normalized in ("csv",):
        return TabularFormat.CSV
    return TabularFormat.XLSX

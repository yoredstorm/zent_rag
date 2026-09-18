# =============================================================================
# Tabular ingestion — lectura de valores XLSX (openpyxl read_only)
# =============================================================================
# Una pasada streaming por hoja (data_only=True → valores cacheados) y, solo si
# el XML reporta formulas, una segunda pasada para conservar el TEXTO de la
# fórmula (nunca se evalúa). Los metadatos estructurales vienen de xlsx_meta.
# =============================================================================
from __future__ import annotations

import datetime as _dt
from uuid import UUID

from src.knowledge.tabular.grid import ExcelTableDef, SheetGrid, WorkbookGrid
from src.knowledge.tabular.xlsx_meta import SheetMeta, XlsxMetaError, read_workbook_meta


class XlsxReadError(ValueError):
    """XLSX ilegible o por encima de límites."""


def read_xlsx_grid(
    data: bytes,
    filename: str,
    *,
    max_sheets: int = 50,
    max_rows_per_sheet: int = 100_000,
    max_columns: int = 512,
    max_cells: int = 2_000_000,
    capture_formulas: bool = True,
) -> WorkbookGrid:
    """Workbook → WorkbookGrid (valores + metadatos) con límites duros."""
    try:
        meta = read_workbook_meta(data)
    except XlsxMetaError as exc:
        raise XlsxReadError(str(exc)) from exc

    try:
        import openpyxl
        from openpyxl.utils.datetime import from_excel  # noqa: F401  (compat)
    except ImportError as exc:  # pragma: no cover - dependency in pyproject
        raise XlsxReadError("openpyxl is not installed") from exc

    sheets: list[SheetGrid] = []
    truncated = False
    limits_hit: list[str] = []
    consumed_cells = 0

    meta_by_name = {sheet.name: sheet for sheet in meta.sheets}

    try:
        values_book = openpyxl.load_workbook(
            _buffer(data), read_only=True, data_only=True, keep_links=False
        )
    except Exception as exc:
        raise XlsxReadError(f"workbook could not be opened: {exc}") from exc

    formula_book = None
    try:
        for index, name in enumerate(values_book.sheetnames):
            if len(sheets) >= max_sheets:
                truncated = True
                limits_hit.append("max_sheets")
                break
            sheet_meta = meta_by_name.get(name) or SheetMeta(
                name=name, path="", state="visible"
            )
            try:
                sheet = values_book[name]
            except KeyError:
                continue
            grid, sheet_truncated, sheet_limits = _read_sheet_values(
                sheet=sheet,
                sheet_meta=sheet_meta,
                index=index,
                max_rows=max_rows_per_sheet,
                max_columns=max_columns,
                remaining_cells=max(0, max_cells - consumed_cells),
            )
            consumed_cells += grid.non_empty_cells
            truncated = truncated or sheet_truncated
            limits_hit.extend(sheet_limits)

            if capture_formulas and sheet_meta.formula_count > 0:
                if formula_book is None:
                    try:
                        formula_book = openpyxl.load_workbook(
                            _buffer(data), read_only=True, data_only=False, keep_links=False
                        )
                    except Exception:  # pragma: no cover - best effort
                        formula_book = None
                if formula_book is not None and name in formula_book.sheetnames:
                    grid = _attach_formulas(formula_book[name], grid, max_columns)

            sheets.append(grid)
    finally:
        values_book.close()
        if formula_book is not None:
            formula_book.close()

    if not sheets:
        raise XlsxReadError(f"workbook has no readable sheets: {filename}")

    return WorkbookGrid(
        filename=filename,
        format="xlsx",
        sheets=tuple(sheets),
        source_bytes=len(data),
        truncated=truncated,
        limits_hit=tuple(dict.fromkeys(limits_hit)),
        metadata={"xlsx_meta_truncated": meta.truncated},
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _buffer(data: bytes):
    import io

    return io.BytesIO(data)


def _read_sheet_values(
    *,
    sheet,
    sheet_meta: SheetMeta,
    index: int,
    max_rows: int,
    max_columns: int,
    remaining_cells: int,
) -> tuple[SheetGrid, bool, list[str]]:
    truncated = False
    limits_hit: list[str] = []

    dimension = sheet_meta.dimension
    declared_max_col = dimension.max_col if dimension else None
    try:
        sheet_max_col = int(sheet.max_column or 1)
    except Exception:  # pragma: no cover - read_only quirk
        sheet_max_col = 1
    if declared_max_col is None:
        # Sin dimensión declarada (p. ej. write_only workbooks) no se puede
        # confiar en max_column: se lee sin cap y se trunca por fila.
        width: int | None = None
    else:
        width = max(declared_max_col, sheet_max_col, 1)
        if width > max_columns:
            width = max_columns
            truncated = True
            limits_hit.append("max_columns")

    raw_rows: list[tuple[int, tuple[str, ...]]] = []
    cell_budget = max(0, remaining_cells)
    cell_count = 0
    try:
        if width is None:
            iterator = sheet.iter_rows(min_row=1, values_only=True)
        else:
            iterator = sheet.iter_rows(min_row=1, max_col=width, values_only=True)
    except Exception as exc:  # pragma: no cover - corrupt sheet
        raise XlsxReadError(f"sheet {sheet_meta.name!r} could not be iterated: {exc}") from exc

    for row_number, row in enumerate(iterator, start=1):
        if row_number > max_rows:
            truncated = True
            limits_hit.append("max_rows_per_sheet")
            break
        values = tuple(_stringify(value) for value in row)
        if width is None and len(values) > max_columns:
            values = values[:max_columns]
            truncated = True
            if "max_columns" not in limits_hit:
                limits_hit.append("max_columns")
        if cell_count + len(values) > cell_budget:
            truncated = True
            limits_hit.append("max_cells")
            break
        cell_count += len(values)
        if not any(value != "" for value in values):
            continue
        raw_rows.append((row_number, values))

    min_col, max_col = 1, width or 1
    if raw_rows:
        used_cols = [
            column
            for _row, values in raw_rows
            for column, value in enumerate(values, start=1)
            if value != ""
        ]
        if used_cols:
            min_col = min(used_cols)
            max_col = max(used_cols)

    rows: list[tuple[int, tuple[str, ...]]] = []
    for row_number, values in raw_rows:
        dense = tuple(values[min_col - 1 : max_col])
        if not any(value != "" for value in dense):
            continue
        rows.append((row_number, dense))

    grid = SheetGrid(
        name=sheet_meta.name,
        index=index,
        min_col=min_col,
        max_col=max_col,
        rows=tuple(rows),
        merged=tuple(sheet_meta.merged),
        hidden_rows=sheet_meta.hidden_rows,
        hidden_columns=frozenset(
            column
            for column in sheet_meta.hidden_columns
            if min_col <= column <= max_col
        ),
        excel_tables=tuple(
            ExcelTableDef(
                name=table.name,
                ref=table.ref,
                header_row_count=table.header_row_count,
                totals_row_count=table.totals_row_count,
                columns=table.columns,
            )
            for table in sheet_meta.excel_tables
            if table.ref is not None
        ),
        hidden=sheet_meta.state != "visible",
        state=sheet_meta.state,
        truncated=truncated,
        limits_hit=tuple(dict.fromkeys(limits_hit)),
        metadata={"formula_count": sheet_meta.formula_count},
    )
    return grid, truncated, limits_hit


def _attach_formulas(formula_sheet, grid: SheetGrid, max_columns: int) -> SheetGrid:
    formulas: dict[tuple[int, int], str] = {}
    restore: dict[tuple[int, int], str] = {}
    try:
        iterator = formula_sheet.iter_rows(min_row=1, max_col=max_columns)
    except Exception:  # pragma: no cover - best effort
        return grid
    for row_number, row in enumerate(iterator, start=1):
        for column, cell in enumerate(row, start=1):
            value = getattr(cell, "value", None)
            if isinstance(value, str) and value.startswith("="):
                formulas[(row_number, column)] = value
            # El valor crudo (no evaluado) se conserva como raw si la celda
            # tenía fórmula: la semántica exacta del archivo queda trazable.
    if not formulas:
        return grid
    return SheetGrid(
        name=grid.name,
        index=grid.index,
        min_col=grid.min_col,
        max_col=grid.max_col,
        rows=grid.rows,
        formulas=formulas,
        merged=grid.merged,
        hidden_rows=grid.hidden_rows,
        hidden_columns=grid.hidden_columns,
        excel_tables=grid.excel_tables,
        hidden=grid.hidden,
        state=grid.state,
        truncated=grid.truncated,
        limits_hit=grid.limits_hit,
        metadata={**grid.metadata, "formulas_captured": len(formulas)},
    )


def _stringify(value: object) -> str:
    """String exacto (no destructivo con códigos); fechas en ISO-8601."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, _dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, _dt.time):
        return value.isoformat()
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, UUID):  # pragma: no cover - defensive
        return str(value)
    return str(value)

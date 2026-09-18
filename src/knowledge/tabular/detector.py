# =============================================================================
# Tabular ingestion — detección de regiones tabulares y encabezados
# =============================================================================
# Determinista (sin LLM, sin abrir estilos): ocupación de celdas → bandas de
# filas y runs de columnas → regiones → scoring de encabezado (incluye
# multinivel y merged cells) → contexto (título/subtítulo/nota).
#
# Prioridad: Tables formales de Excel > structured references > heurística.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.tabular import (
    CellRange,
    TabularContextBlock,
    TabularContextKind,
    TabularDetectionMethod,
    TabularValueType,
)
from src.knowledge.tabular.grid import ExcelTableDef, SheetGrid
from src.knowledge.tabular.schema import (
    classify_value,
    is_probable_header_row,
)

_MAX_HEADER_ROWS = 4
_MIN_HEADER_CONFIDENCE = 0.35
_CONTEXT_LOOKBACK = 5


@dataclass(kw_only=True)
class DetectedTable:
    """Región tabular detectada (previa a la construcción de columnas/filas)."""

    name: str
    sheet_name: str
    sheet_index: int
    table_range: CellRange
    header_rows: tuple[int, ...] = ()
    column_names: tuple[str, ...] = ()
    column_labels: tuple[tuple[str, ...], ...] = ()
    data_start_row: int = 1
    detection_method: TabularDetectionMethod = TabularDetectionMethod.HEURISTIC
    detection_confidence: float = 0.0
    header_confidence: float = 0.0
    title: str = ""
    context: tuple[TabularContextBlock, ...] = ()
    excel_table: ExcelTableDef | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def header_depth(self) -> int:
        return len(self.header_rows)

    @property
    def column_columns(self) -> tuple[int, ...]:
        return tuple(
            range(self.table_range.min_col, self.table_range.min_col + len(self.column_names))
        )


@dataclass(kw_only=True)
class DetectedSheet:
    sheet_name: str
    sheet_index: int
    tables: tuple[DetectedTable, ...] = ()
    context: tuple[TabularContextBlock, ...] = ()
    free_cells: int = 0
    metadata: dict = field(default_factory=dict)


def detect_sheet_tables(grid: SheetGrid) -> DetectedSheet:
    """Detecta todas las tablas de una hoja + contexto libre."""
    if not grid.rows:
        return DetectedSheet(sheet_name=grid.name, sheet_index=grid.index)

    occupied: dict[int, dict[int, str]] = {}
    for row_number, values in grid.rows:
        row_values: dict[int, str] = {}
        for offset, value in enumerate(values):
            if value != "":
                row_values[grid.min_col + offset] = value
        if row_values:
            occupied[row_number] = row_values

    consumed: set[tuple[int, int]] = set()
    detected: list[DetectedTable] = []

    # 1) Tables formales de Excel (autoritativas). Marcan sus celdas como
    # consumidas de inmediato para que la heurística no las re-detecte.
    for excel_table in sorted(
        (table for table in grid.excel_tables if table.ref is not None),
        key=lambda table: (table.ref.min_row, table.ref.min_col),
    ):
        table = _detect_formal_table(grid, excel_table, occupied, consumed)
        if table is not None:
            detected.append(table)
            for row_number in range(
                table.table_range.min_row, table.table_range.max_row + 1
            ):
                for column in range(
                    table.table_range.min_col, table.table_range.max_col + 1
                ):
                    if occupied.get(row_number, {}).get(column, "") != "":
                        consumed.add((row_number, column))

    # 2) Heurística sobre las celdas no consumidas.
    bands = _row_bands(occupied, consumed)
    for band in bands:
        for column_run in _column_runs(band, occupied, consumed, grid):
            table = _detect_heuristic_region(grid, band, column_run, occupied, consumed)
            if table is not None:
                detected.append(table)

    detected.sort(key=lambda table: (table.table_range.min_row, table.table_range.min_col))
    detected = _drop_single_column_titles(detected)
    _attach_context_and_names(detected, grid, occupied)

    # 3) Contexto de hoja: celdas fuera de tablas (títulos sueltos, notas).
    #    O(celdas) una sola vez; las celdas dentro de tablas se descartan por
    #    rango (no hace falta marcar consumed para el conteo).
    table_regions = [table.table_range for table in detected]
    sheet_context: list[TabularContextBlock] = []
    free_cells = 0
    for row_number, row_values in occupied.items():
        inside_table = any(region.min_row <= row_number <= region.max_row for region in table_regions)
        for column, value in row_values.items():
            if (row_number, column) in consumed:
                continue
            if inside_table and any(
                region.contains(row_number, column) for region in table_regions
            ):
                continue
            free_cells += 1
            if len(value.strip()) >= 4:
                sheet_context.append(
                    TabularContextBlock(
                        text=value.strip()[:500],
                        kind=TabularContextKind.NOTE,
                        physical_row=row_number,
                        physical_column=column,
                        confidence=0.3,
                    )
                )

    return DetectedSheet(
        sheet_name=grid.name,
        sheet_index=grid.index,
        tables=tuple(detected),
        context=tuple(sheet_context[:20]),
        free_cells=free_cells,
    )


# ---------------------------------------------------------------------------
# Tables formales
# ---------------------------------------------------------------------------


def _detect_formal_table(
    grid: SheetGrid,
    excel_table: ExcelTableDef,
    occupied: dict[int, dict[int, str]],
    consumed: set[tuple[int, int]],
) -> DetectedTable | None:
    ref = excel_table.ref
    if ref is None:  # pragma: no cover - defensive
        return None
    header_count = max(1, min(excel_table.header_row_count or 1, _MAX_HEADER_ROWS))
    last_header = min(ref.min_row + header_count - 1, ref.max_row)
    header_rows = tuple(range(ref.min_row, last_header + 1))
    column_names = _column_names_from_headers(grid, header_rows, ref)
    if not column_names and excel_table.columns:
        column_names = tuple(
            name or f"Column {index + 1}"
            for index, name in enumerate(excel_table.columns[: ref.column_count])
        )
    data_start = max(header_rows) + 1 if header_rows else ref.min_row
    if excel_table.totals_row_count and ref.max_row - data_start + 1 >= excel_table.totals_row_count:
        pass  # la fila de totales se conserva como dato (no se descarta información)
    return DetectedTable(
        name=excel_table.name or f"{grid.name} Table",
        sheet_name=grid.name,
        sheet_index=grid.index,
        table_range=ref,
        header_rows=header_rows,
        column_names=column_names,
        column_labels=tuple((name,) for name in column_names),
        data_start_row=data_start,
        detection_method=TabularDetectionMethod.EXCEL_TABLE,
        detection_confidence=1.0,
        header_confidence=1.0 if column_names else 0.8,
        title=excel_table.name,
        context=(),
        excel_table=excel_table,
        metadata={"header_row_count": excel_table.header_row_count},
    )


def _column_names_from_headers(
    grid: SheetGrid, header_rows: tuple[int, ...], ref: CellRange
) -> tuple[str, ...]:
    """Nombres de columna desde la última fila de header (herencia de merged)."""
    if not header_rows:
        return ()
    header_row = max(header_rows)
    values = _row_slice(grid, header_row, ref.min_col, ref.max_col)
    names: list[str] = []
    for index, value in enumerate(values):
        name = value.strip()
        if not name:
            column = ref.min_col + index
            for merge in grid.merged:
                if (
                    merge.min_row == header_row
                    and merge.min_col <= column <= merge.max_col
                ):
                    name = _cell_value(grid, header_row, merge.min_col).strip()
                    break
        names.append(name)
    while names and not names[-1]:
        names.pop()
    return tuple(names)


# ---------------------------------------------------------------------------
# Bandas y regiones
# ---------------------------------------------------------------------------


def _row_bands(
    occupied: dict[int, dict[int, str]], consumed: set[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Bandas [first_row, last_row] separadas por filas totalmente vacías."""
    rows: list[int] = []
    for row_number, row_values in occupied.items():
        if any((row_number, column) not in consumed for column in row_values):
            rows.append(row_number)
    rows.sort()
    bands: list[tuple[int, int]] = []
    start: int | None = None
    previous: int | None = None
    for row_number in rows:
        if start is None:
            start = previous = row_number
            continue
        if row_number == previous + 1:
            previous = row_number
            continue
        bands.append((start, previous))
        start = previous = row_number
    if start is not None and previous is not None:
        bands.append((start, previous))
    return bands


def _column_runs(
    band: tuple[int, int],
    occupied: dict[int, dict[int, str]],
    consumed: set[tuple[int, int]],
    grid: SheetGrid,
) -> list[tuple[int, int]]:
    """Runs de columnas contiguas con datos dentro de la banda (tablas lado a lado)."""
    columns: set[int] = set()
    for row_number in range(band[0], band[1] + 1):
        for column in occupied.get(row_number, {}):
            if (row_number, column) not in consumed:
                columns.add(column)
    if not columns:
        return []
    ordered = sorted(columns)
    runs: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for column in ordered[1:]:
        if column == previous + 1:
            previous = column
            continue
        runs.append((start, previous))
        start = previous = column
    runs.append((start, previous))
    return runs


# ---------------------------------------------------------------------------
# Detección heurística
# ---------------------------------------------------------------------------


def _detect_heuristic_region(
    grid: SheetGrid,
    band: tuple[int, int],
    column_run: tuple[int, int],
    occupied: dict[int, dict[int, str]],
    consumed: set[tuple[int, int]],
) -> DetectedTable | None:
    first_row, last_row = band
    min_col, max_col = column_run
    if last_row < first_row or max_col < min_col:
        return None
    rows_with_data = [
        row_number
        for row_number in range(first_row, last_row + 1)
        if any(
            (row_number, column) not in consumed
            for column in occupied.get(row_number, {})
            if min_col <= column <= max_col
        )
    ]
    if not rows_with_data:
        return None
    table_range = CellRange(
        min_row=rows_with_data[0], max_row=rows_with_data[-1], min_col=min_col, max_col=max_col
    )
    # Una sola celda no es tabla (es contexto libre).
    if table_range.cell_count == 1 or (
        table_range.row_count == 1 and table_range.column_count == 1
    ):
        return None

    header_choice = _choose_header_rows(grid, rows_with_data, table_range)
    if header_choice is None:
        return None
    header_rows, header_confidence, labels = header_choice
    if header_confidence < _MIN_HEADER_CONFIDENCE:
        return None

    data_rows_in_region = [
        row_number for row_number in rows_with_data if row_number > max(header_rows)
    ]
    # Región de una sola columna con menos de dos filas de datos: es texto
    # (título/nota), no una tabla. Evita falsos positivos de bandas de título.
    if table_range.column_count == 1 and len(data_rows_in_region) < 2:
        return None

    column_names: list[str] = []
    for labels_for_column in labels:
        name = labels_for_column[-1].strip() if labels_for_column else ""
        column_names.append(name or f"Column {len(column_names) + 1}")
    data_start = max(header_rows) + 1
    table_range = CellRange(
        min_row=min(header_rows),
        max_row=table_range.max_row,
        min_col=min_col,
        max_col=max_col,
    )
    detection_confidence = _detection_confidence(
        occupied, rows_with_data, table_range, header_rows, consumed
    )
    return DetectedTable(
        name=f"{grid.name} table {table_range.min_row}:{min_col}-{len(column_names)}",
        sheet_name=grid.name,
        sheet_index=grid.index,
        table_range=table_range,
        header_rows=tuple(header_rows),
        column_names=tuple(column_names),
        column_labels=tuple(labels),
        data_start_row=data_start,
        detection_method=TabularDetectionMethod.HEURISTIC,
        detection_confidence=detection_confidence,
        header_confidence=header_confidence,
        title="",
        context=(),
        metadata={"band": [first_row, last_row]},
    )


def _choose_header_rows(
    grid: SheetGrid,
    rows_with_data: list[int],
    table_range: CellRange,
) -> tuple[tuple[int, ...], float, tuple[tuple[str, ...], ...]] | None:
    """Elige fila(s) de encabezado. Devuelve (filas, confianza, labels por columna)."""
    width = table_range.column_count
    candidates: list[tuple[float, int]] = []
    for index, row_number in enumerate(rows_with_data[:_MAX_HEADER_ROWS]):
        values = _row_slice(grid, row_number, table_range.min_col, table_range.max_col)
        score = _header_score(
            grid, row_number, values, rows_with_data, index, width, table_range
        )
        if score > 0:
            candidates.append((score, row_number))
    if not candidates:
        return None
    best_score, best_row = max(candidates, key=lambda item: item[0])
    if best_score < _MIN_HEADER_CONFIDENCE:
        return None

    # Multinivel: filas por encima con merged cells o varias celdas que
    # aplican a columnas contiguas (super-headers tipo "Position").
    header_rows: list[int] = [best_row]
    merged_lookup = {merge.min_row: merge for merge in grid.merged}
    upper_row = best_row - 1
    levels = 0
    while levels < 2 and upper_row in rows_with_data:
        merged = merged_lookup.get(upper_row)
        values = _row_slice(grid, upper_row, table_range.min_col, table_range.max_col)
        non_empty = [value.strip() for value in values if value.strip()]
        merged_span = (
            merged is not None
            and merged.max_col > merged.min_col
            and merged.min_col >= table_range.min_col
            and merged.max_col <= table_range.max_col
        )
        if merged_span or (
            best_row - upper_row >= 1
            and len(non_empty) >= 2
            and len(non_empty) <= max(1, (width + 1) // 2)
            and all(len(value) <= 40 for value in non_empty)
            and not any(classify_value(value) is TabularValueType.MIXED for value in non_empty)
            and all(
                classify_value(value)
                in (
                    TabularValueType.STRING,
                    TabularValueType.CODE,
                    TabularValueType.IDENTIFIER,
                )
                for value in non_empty
            )
        ):
            header_rows.insert(0, upper_row)
            levels += 1
            upper_row -= 1
            continue
        break

    labels = _build_column_labels(grid, header_rows, table_range)
    if len(labels) > 1 and any(len(label) > 1 for label in labels):
        header_confidence = min(1.0, best_score + 0.1)
    else:
        header_confidence = best_score
    return tuple(sorted(header_rows)), round(header_confidence, 3), labels


def _header_score(
    grid: SheetGrid,
    row_number: int,
    values: tuple[str, ...],
    rows_with_data: list[int],
    position: int,
    width: int,
    table_range: CellRange,
) -> float:
    non_empty = [value.strip() for value in values if value.strip()]
    if not non_empty:
        return 0.0
    score = 0.0
    if is_probable_header_row(non_empty):
        score += 0.45
    fill_ratio = len(non_empty) / max(1, width)
    score += 0.2 * min(1.0, fill_ratio / 0.6)
    if len(set(non_empty)) == len(non_empty):
        score += 0.1
    if all(len(value) <= 80 for value in non_empty):
        score += 0.05
    # Señal fuerte: la fila siguiente tiene tipos NO textuales donde el
    # encabezado es texto. No se exige mayoría numérica: tablas densas con
    # columnas de texto + códigos (p. ej. diccionarios ATPCO) también cuentan.
    next_rows = [row for row in rows_with_data if row > row_number]
    if next_rows:
        next_values = [
            value
            for value in _row_slice(
                grid, next_rows[0], table_range.min_col, table_range.max_col
            )
            if value.strip()
        ]
        non_text_next = sum(
            1
            for value in next_values
            if classify_value(value)
            not in (TabularValueType.STRING, TabularValueType.UNKNOWN)
        )
        if non_text_next >= max(2, len(next_values) // 4):
            score += 0.2
    if position == 0:
        score += 0.05
    # Si la fila es un título suelto (una sola celda sin merged sobre varias
    # columnas) penalizar: los títulos se conservan como contexto, no header.
    merged_spans = {
        merge.min_row: merge
        for merge in grid.merged
        if merge.max_col > merge.min_col
        and merge.min_col >= table_range.min_col
        and merge.max_col <= table_range.max_col
    }
    if len(non_empty) == 1:
        merged = merged_spans.get(row_number)
        if width >= 2 and merged is None:
            score -= 0.3
    return max(0.0, min(1.0, score))


def _build_column_labels(
    grid: SheetGrid, header_rows: tuple[int, ...], table_range: CellRange
) -> tuple[tuple[str, ...], ...]:
    """Labels por columna respetando merged cells (multi-nivel)."""
    merged_by_row = {}
    for merge in grid.merged:
        merged_by_row.setdefault(merge.min_row, []).append(merge)
    labels: list[list[str]] = [[] for _ in range(table_range.column_count)]
    for row_number in header_rows:
        values = _row_slice(grid, row_number, table_range.min_col, table_range.max_col)
        for index in range(table_range.column_count):
            column = table_range.min_col + index
            value = values[index].strip() if index < len(values) else ""
            if not value:
                # Celda vacía dentro de un merged range → hereda el valor ancla.
                for merge in merged_by_row.get(row_number, []):
                    if merge.min_col <= column <= merge.max_col:
                        anchor = _cell_value(grid, row_number, merge.min_col)
                        if anchor:
                            value = anchor.strip()
                            break
            if value and (not labels[index] or labels[index][-1] != value):
                labels[index].append(value)
    return tuple(tuple(label) for label in labels)


def _drop_single_column_titles(tables: list[DetectedTable]) -> list[DetectedTable]:
    """Descarta pseudo-tablas de una columna que son títulos/notas.

    - Si están a <= 6 filas por encima de otra tabla con columnas solapadas,
      son contexto de esa tabla (nunca una tabla de datos).
    - Si todos sus valores son texto largo (> 40 chars), son prosa.
    """
    kept: list[DetectedTable] = []
    for table in tables:
        if table.table_range.column_count != 1:
            kept.append(table)
            continue
        column = table.table_range.min_col
        has_table_below = any(
            other is not table
            and other.table_range.min_row > table.table_range.max_row
            and other.table_range.min_row - table.table_range.max_row <= 6
            and other.table_range.min_col <= column <= other.table_range.max_col
            for other in tables
        )
        if has_table_below:
            continue
        kept.append(table)
    return kept


def _attach_context_and_names(
    tables: list[DetectedTable],
    grid: SheetGrid,
    occupied: dict[int, dict[int, str]],
) -> None:
    """Segunda pasada: contexto de cada tabla sin invadir OTRAS tablas.

    El título puede estar en una banda anterior (caso ATPCO) pero nunca dentro
    del rango de otra tabla detectada (caso dos tablas en una hoja).
    """
    for table in tables:
        other_ranges = [
            other.table_range for other in tables if other is not table
        ]
        context = _context_above(
            grid,
            occupied,
            min(table.header_rows) if table.header_rows else table.table_range.min_row,
            table.table_range.min_col,
            table.table_range.max_col,
            excluded=other_ranges,
        )
        if table.detection_method is TabularDetectionMethod.HEURISTIC:
            title = next(
                (
                    block.text
                    for block in context
                    if block.kind is TabularContextKind.TITLE and block.text.strip()
                ),
                "",
            )
            if title:
                table.title = title[:120]
                table.name = title[:120]
        elif not table.title:
            table.title = table.name
        table.context = context


def _context_above(
    grid: SheetGrid,
    occupied: dict[int, dict[int, str]],
    header_row: int,
    min_col: int,
    max_col: int,
    *,
    excluded: list[CellRange] | None = None,
) -> tuple[TabularContextBlock, ...]:
    """Título/subtítulo/notas inmediatamente encima del header (hasta 5 filas)."""
    context: list[TabularContextBlock] = []
    excluded = excluded or []
    rows = sorted(
        (
            row_number
            for row_number in occupied
            if header_row - _CONTEXT_LOOKBACK <= row_number < header_row
            and not any(
                region.contains(row_number, min_col)
                and region.contains(row_number, max_col)
                for region in excluded
            )
        )
    )
    for row_number in rows:
        values = [
            (column, occupied[row_number][column])
            for column in sorted(occupied.get(row_number, {}))
            if min_col - 2 <= column <= max_col + 2
        ]
        if not values:
            continue
        for column, value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > 300:
                text = text[:300]
            # Orden de lectura: la primera fila es el título, la siguiente el
            # subtítulo y el resto notas. Siempre es contexto, nunca header.
            kind = TabularContextKind.TITLE if not context else (
                TabularContextKind.SUBTITLE if len(context) == 1 else TabularContextKind.NOTE
            )
            context.append(
                TabularContextBlock(
                    text=text,
                    kind=kind,
                    physical_row=row_number,
                    physical_column=column,
                    range=CellRange(
                        min_row=row_number, max_row=row_number, min_col=column, max_col=column
                    ),
                    confidence=0.7 if kind is TabularContextKind.TITLE else 0.5,
                )
            )
    return tuple(context)


def _detection_confidence(
    occupied: dict[int, dict[int, str]],
    rows_with_data: list[int],
    table_range: CellRange,
    header_rows: tuple[int, ...],
    consumed: set[tuple[int, int]],
) -> float:
    cells = table_range.cell_count
    filled = sum(
        1
        for row_number in rows_with_data
        for column in occupied.get(row_number, {})
        if (row_number, column) not in consumed
    )
    density = filled / max(1, cells)
    data_rows = len([row for row in rows_with_data if row > max(header_rows)])
    score = 0.4 + 0.3 * min(1.0, density / 0.6) + 0.3 * min(1.0, data_rows / 5)
    return round(min(1.0, score), 3)


# ---------------------------------------------------------------------------
# Helpers de acceso al grid
# ---------------------------------------------------------------------------


def _row_slice(grid: SheetGrid, row_number: int, min_col: int, max_col: int) -> tuple[str, ...]:
    values = grid.row_values(row_number)
    if values is None:
        return ()
    start = max(0, min_col - grid.min_col)
    end = max(0, max_col - grid.min_col + 1)
    result = values[start:end]
    if len(result) < (max_col - min_col + 1):
        result = tuple(result) + ("",) * (max_col - min_col + 1 - len(result))
    return tuple(result)


def _cell_value(grid: SheetGrid, row_number: int, column: int) -> str:
    values = grid.row_values(row_number)
    if values is None:
        return ""
    offset = column - grid.min_col
    if 0 <= offset < len(values):
        return values[offset]
    return ""

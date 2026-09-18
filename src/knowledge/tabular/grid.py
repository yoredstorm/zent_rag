# =============================================================================
# Tabular ingestion — grid normalizado (valores + metadatos físicos)
# =============================================================================
# `SheetGrid` es la entrada común de los parsers XLSX/CSV al pipeline tabular:
# filas con valores alineados a columnas, filas/columnas ocultas, celdas
# combinadas, formulas y Tables formales de Excel. No es el modelo de dominio:
# es el sustrato de profiling/detección.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field

from src.core.domain.tabular import CellRange


@dataclass(frozen=True, kw_only=True)
class ExcelTableDef:
    """Table formal de Excel (xl/tables/tableN.xml)."""

    name: str
    ref: CellRange
    header_row_count: int = 1
    totals_row_count: int = 0
    columns: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SheetGrid:
    """Hoja normalizada: solo filas con al menos un valor no vacío.

    `rows` es una lista ordenada de (fila_física, valores) donde `values` está
    alineado a [min_col, max_col] (inclusive). Los separadores de filas/columnas
    se derivan de los huecos entre filas físicas y columnas vacías.

    `non_empty_cells`, `non_empty_rows` y `used_range()` se calculan una sola
    vez (memo en __dict__; el dataclass es frozen pero eso no bloquea la caché)
    para no recorrer 100k filas en cada fase del pipeline.
    """

    name: str
    index: int
    min_col: int = 1
    max_col: int = 1
    rows: tuple[tuple[int, tuple[str, ...]], ...] = ()
    formulas: dict[tuple[int, int], str] = field(default_factory=dict)
    merged: tuple[CellRange, ...] = ()
    hidden_rows: frozenset[int] = frozenset()
    hidden_columns: frozenset[int] = frozenset()
    excel_tables: tuple[ExcelTableDef, ...] = ()
    hidden: bool = False
    state: str = "visible"
    truncated: bool = False
    limits_hit: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max(0, self.max_col - self.min_col + 1)

    @property
    def non_empty_cells(self) -> int:
        return self._memo("_non_empty_cells", self._count_non_empty_cells)

    @property
    def non_empty_rows(self) -> int:
        return self._memo("_non_empty_rows", self._count_non_empty_rows)

    def _count_non_empty_cells(self) -> int:
        return sum(
            1 for _row, values in self.rows for value in values if value != ""
        )

    def _count_non_empty_rows(self) -> int:
        return sum(1 for _row, values in self.rows if any(v != "" for v in values))

    def _memo(self, key: str, factory):
        missing = object()
        cached = self.__dict__.get(key, missing)
        if cached is missing:
            cached = factory()
            object.__setattr__(self, key, cached)
        return cached

    def value(self, physical_row: int, physical_column: int) -> str:
        """Valor en coordenadas físicas (lookup O(log n) por búsqueda binaria)."""
        values = self.row_values(physical_row)
        if values is None:
            return ""
        offset = physical_column - self.min_col
        if 0 <= offset < len(values):
            return values[offset]
        return ""

    def row_values(self, physical_row: int) -> tuple[str, ...] | None:
        """Valores de una fila física. `rows` está ordenado por fila → bisect."""
        import bisect

        index = bisect.bisect_left(self.rows, (physical_row,))
        if index < len(self.rows) and self.rows[index][0] == physical_row:
            return self.rows[index][1]
        return None

    def iter_non_empty_rows(self):
        """Genera (physical_row, values) solo con filas que tienen algún valor."""
        for physical_row, values in self.rows:
            if any(value != "" for value in values):
                yield physical_row, values

    def used_range(self) -> CellRange | None:
        return self._memo("_used_range", self._compute_used_range)

    def _compute_used_range(self) -> CellRange | None:
        non_empty = list(self.iter_non_empty_rows())
        if not non_empty:
            return None
        first_row = non_empty[0][0]
        last_row = non_empty[-1][0]
        used_columns = [
            self.min_col + offset
            for _row, values in non_empty
            for offset, value in enumerate(values)
            if value != ""
        ]
        if not used_columns:
            return None
        return CellRange(
            min_row=first_row,
            max_row=last_row,
            min_col=min(used_columns),
            max_col=max(used_columns),
        )


@dataclass(frozen=True, kw_only=True)
class WorkbookGrid:
    """Workbook normalizado listo para profiling/detección."""

    filename: str
    format: str
    sheets: tuple[SheetGrid, ...] = ()
    content_hash: str = ""
    source_bytes: int = 0
    truncated: bool = False
    limits_hit: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(sheet.name for sheet in self.sheets)

    @property
    def non_empty_cells(self) -> int:
        return sum(sheet.non_empty_cells for sheet in self.sheets)

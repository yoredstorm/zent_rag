# =============================================================================
# Domain Layer — Tabular knowledge model (Knowledge Tabular V2)
# =============================================================================
# Modelo puro (sin I/O) para hojas de cálculo y CSV: workbook → sheet → table →
# column/row/cell, con posiciones físicas (fila/columna Excel, address) y
# semánticas (start_position, length, ...), tipos, metadata y provenance.
#
# Regla de oro: una tabla NO es texto. La serialización para embeddings es una
# vista derivada; la estructura canónica es este árbol.
#
# Los identificadores son deterministas (uuid5 en src/knowledge/tabular/ids.py)
# para que re-ingestar el mismo archivo sea idempotente y permita updates
# incrementales por fila.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from src.core.domain.catalog import CatalogProvenance

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TabularFormat(StrEnum):
    """Formato físico del workbook."""

    XLSX = "xlsx"
    XLSM = "xlsm"
    XLS = "xls"
    CSV = "csv"
    TSV = "tsv"


class TabularValueType(StrEnum):
    """Tipo físico inferido de una columna (determinista)."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    CODE = "code"
    IDENTIFIER = "identifier"
    URL = "url"
    EMAIL = "email"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class TabularSemanticType(StrEnum):
    """Tipo semántico (código/descripción/posición/...). Puede ser inferido."""

    IDENTIFIER = "identifier"
    CODE = "code"
    NAME = "name"
    DESCRIPTION = "description"
    POSITION = "position"
    LENGTH = "length"
    OFFSET = "offset"
    QUANTITY = "quantity"
    AMOUNT = "amount"
    PERCENTAGE = "percentage"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    CATEGORY = "category"
    REFERENCE = "reference"
    FREE_TEXT = "free_text"
    UNKNOWN = "unknown"


class TabularMetadataOrigin(StrEnum):
    """Trazabilidad de metadata (brief §5): de dónde salió cada inferencia."""

    SOURCE = "SOURCE"  # leído del archivo (header cell, Excel Table, etc.)
    DETERMINISTIC = "DETERMINISTIC"  # algoritmo local sin LLM
    INFERRED = "INFERRED"  # heurística con confidence < 1
    LLM_INFERRED = "LLM_INFERRED"  # enriquecimiento semántico por LLM


class TabularDetectionMethod(StrEnum):
    """Cómo se detectó una tabla."""

    EXCEL_TABLE = "excel_table"  # Table formal de Excel (openpyxl ws.tables)
    STRUCTURED_REFERENCE = "structured_reference"  # fórmula =Table[...]
    HEURISTIC = "heuristic"
    CSV_SINGLE = "csv_single"


class TabularRelationKind(StrEnum):
    """Candidatos de relación entre tablas (nunca se ejecutan joins solos)."""

    CANDIDATE_JOIN = "candidate_join"
    CANDIDATE_LOOKUP = "candidate_lookup"
    CANDIDATE_HIERARCHY = "candidate_hierarchy"


class TabularContextKind(StrEnum):
    """Contexto alrededor de una región tabular (título, subtítulo, nota)."""

    TITLE = "title"
    SUBTITLE = "subtitle"
    NOTE = "note"
    FOOTER = "footer"
    HEADER_NOTE = "header_note"


class TabularQualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class TabularChangeKind(StrEnum):
    """Cambio de una tabla/workbook en re-ingesta (brief §12)."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    UPDATED = "updated"
    SCHEMA_CHANGED = "schema_changed"


# ---------------------------------------------------------------------------
# Geometría / direccionamiento
# ---------------------------------------------------------------------------


def column_letter(physical_column: int) -> str:
    """1 → 'A', 27 → 'AA' (1-based, como Excel)."""
    if physical_column < 1:
        raise ValueError(f"physical_column must be >= 1, got {physical_column}")
    letters = ""
    value = physical_column
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def cell_address(physical_row: int, physical_column: int) -> str:
    """(35, 2) → 'B35'."""
    if physical_row < 1:
        raise ValueError(f"physical_row must be >= 1, got {physical_row}")
    return f"{column_letter(physical_column)}{physical_row}"


@dataclass(frozen=True, kw_only=True)
class CellRange:
    """Región rectangular en coordenadas físicas (1-based, inclusivas)."""

    min_row: int
    max_row: int
    min_col: int
    max_col: int

    def __post_init__(self) -> None:
        if self.min_row < 1 or self.min_col < 1:
            raise ValueError(
                f"CellRange requires 1-based coordinates, got {self.min_row}:{self.min_col}"
            )
        if self.max_row < self.min_row or self.max_col < self.min_col:
            raise ValueError(
                f"CellRange must satisfy max >= min, got rows {self.min_row}-{self.max_row} "
                f"cols {self.min_col}-{self.max_col}"
            )

    @property
    def row_count(self) -> int:
        return self.max_row - self.min_row + 1

    @property
    def column_count(self) -> int:
        return self.max_col - self.min_col + 1

    @property
    def cell_count(self) -> int:
        return self.row_count * self.column_count

    def contains(self, physical_row: int, physical_column: int) -> bool:
        return (
            self.min_row <= physical_row <= self.max_row
            and self.min_col <= physical_column <= self.max_col
        )

    def to_dict(self) -> dict:
        return {
            "min_row": self.min_row,
            "max_row": self.max_row,
            "min_col": self.min_col,
            "max_col": self.max_col,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> CellRange:
        return cls(
            min_row=int(raw["min_row"]),
            max_row=int(raw["max_row"]),
            min_col=int(raw["min_col"]),
            max_col=int(raw["max_col"]),
        )


# ---------------------------------------------------------------------------
# Celdas, columnas, filas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TabularCell:
    """Valor físico de una celda con sus metadatos (fórmula, merged, tipo).

    Los detalles de celda se conservan solo cuando aportan algo (fórmula,
    merged, tipo distinto al de la columna). Las celdas triviales se derivan de
    `TabularRow.values` + posición de columna.
    """

    physical_row: int
    physical_column: int
    raw_value: str
    address: str = ""
    normalized_value: str | None = None
    inferred_type: TabularValueType = TabularValueType.UNKNOWN
    formula: str | None = None
    formula_cached_value: str | None = None
    is_merged: bool = False
    merged_range: CellRange | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.address:
            object.__setattr__(
                self, "address", cell_address(self.physical_row, self.physical_column)
            )


@dataclass(frozen=True, kw_only=True)
class TabularColumn:
    """Columna de una tabla con identidad física y semántica."""

    id: UUID
    physical_index: int  # 0-based dentro de la tabla
    physical_column: int  # 1-based absoluta en la hoja
    excel_letter: str
    original_name: str
    normalized_name: str
    aliases: tuple[str, ...] = ()
    header_path: tuple[str, ...] = ()
    inferred_type: TabularValueType = TabularValueType.UNKNOWN
    semantic_type: TabularSemanticType = TabularSemanticType.UNKNOWN
    type_confidence: float = 0.0
    semantic_confidence: float = 0.0
    nullable: bool = True
    null_ratio: float = 0.0
    unique_ratio: float = 0.0
    sample_values: tuple[str, ...] = ()
    description: str = ""
    description_origin: TabularMetadataOrigin = TabularMetadataOrigin.DETERMINISTIC
    metadata_origin: TabularMetadataOrigin = TabularMetadataOrigin.DETERMINISTIC
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.physical_index < 0:
            raise ValueError(
                f"TabularColumn.physical_index must be >= 0, got {self.physical_index}"
            )
        if not 0.0 <= self.type_confidence <= 1.0:
            raise ValueError("TabularColumn.type_confidence must be within [0, 1]")
        if not 0.0 <= self.semantic_confidence <= 1.0:
            raise ValueError("TabularColumn.semantic_confidence must be within [0, 1]")
        for ratio in (self.null_ratio, self.unique_ratio):
            if not 0.0 <= ratio <= 1.0:
                raise ValueError("TabularColumn ratios must be within [0, 1]")

    @property
    def display_name(self) -> str:
        return self.original_name or self.normalized_name


@dataclass(frozen=True, kw_only=True)
class TabularRow:
    """Fila de datos alineada a `TabularTable.columns` (valores raw exactos)."""

    physical_row: int
    logical_index: int
    values: tuple[str, ...] = ()
    cell_details: tuple[TabularCell, ...] = ()
    content_hash: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.physical_row < 1:
            raise ValueError(f"physical_row must be >= 1, got {self.physical_row}")
        if self.logical_index < 0:
            raise ValueError(f"logical_index must be >= 0, got {self.logical_index}")

    def value_at(self, physical_index: int) -> str:
        if 0 <= physical_index < len(self.values):
            return self.values[physical_index]
        return ""

    def value_for(self, column: TabularColumn) -> str:
        return self.value_at(column.physical_index)

    def mapping(self, columns: tuple[TabularColumn, ...]) -> dict[str, str]:
        """{normalized_name: raw_value} — úsese para serialización/metadata."""
        result: dict[str, str] = {}
        for column in columns:
            value = self.value_for(column)
            if value != "":
                result[column.normalized_name] = value
        return result

    def details_for(self, physical_column: int) -> TabularCell | None:
        for detail in self.cell_details:
            if detail.physical_column == physical_column:
                return detail
        return None

    def is_empty(self) -> bool:
        return not any(v.strip() for v in self.values)


@dataclass(frozen=True, kw_only=True)
class TabularContextBlock:
    """Texto alrededor de una tabla (título, subtítulo, nota al pie)."""

    text: str
    kind: TabularContextKind = TabularContextKind.NOTE
    physical_row: int | None = None
    physical_column: int | None = None
    range: CellRange | None = None
    confidence: float = 0.5
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("TabularContextBlock.text must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("TabularContextBlock.confidence must be within [0, 1]")


# ---------------------------------------------------------------------------
# Tabla / hoja / workbook
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TabularTable:
    """Región tabular detectada (o Table formal de Excel) dentro de una hoja."""

    id: UUID
    workbook_id: UUID
    sheet_id: UUID
    name: str
    range: CellRange
    columns: tuple[TabularColumn, ...] = ()
    rows: tuple[TabularRow, ...] = ()
    title: str = ""
    context_lines: tuple[str, ...] = ()
    context_blocks: tuple[TabularContextBlock, ...] = ()
    header_rows: tuple[int, ...] = ()
    header_depth: int = 1
    detection_method: TabularDetectionMethod = TabularDetectionMethod.HEURISTIC
    detection_confidence: float = 0.0
    header_confidence: float = 0.0
    schema_hash: str = ""
    content_hash: str = ""
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("TabularTable.name must not be empty")
        if self.header_depth < 0:
            raise ValueError(f"header_depth must be >= 0, got {self.header_depth}")
        for value, label in (
            (self.detection_confidence, "detection_confidence"),
            (self.header_confidence, "header_confidence"),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"TabularTable.{label} must be within [0, 1]")
        if self.columns:
            indexes = [c.physical_index for c in self.columns]
            if indexes != sorted(indexes):
                raise ValueError("TabularTable.columns must be ordered by physical_index")
        if self.rows and self.columns and any(len(r.values) > len(self.columns) for r in self.rows):
            raise ValueError("TabularRow.values cannot exceed the column count")

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def first_data_row(self) -> int | None:
        if self.rows:
            return self.rows[0].physical_row
        if self.header_rows:
            return max(self.header_rows) + 1
        return self.range.min_row

    @property
    def data_range(self) -> CellRange | None:
        if not self.rows:
            return None
        return CellRange(
            min_row=self.rows[0].physical_row,
            max_row=self.rows[-1].physical_row,
            min_col=self.range.min_col,
            max_col=self.range.max_col,
        )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.original_name for c in self.columns)

    def column_by_name(self, name: str) -> TabularColumn | None:
        wanted = name.strip().lower()
        for column in self.columns:
            if column.normalized_name == _normalize_key(wanted):
                return column
        for column in self.columns:
            if column.original_name.strip().lower() == wanted:
                return column
        for column in self.columns:
            if wanted in (a.lower() for a in column.aliases):
                return column
        return None


@dataclass(frozen=True, kw_only=True)
class TabularSheet:
    """Hoja del workbook: tablas + celdas libres + estado (oculta/visible)."""

    id: UUID
    workbook_id: UUID
    name: str
    index: int
    tables: tuple[TabularTable, ...] = ()
    context_blocks: tuple[TabularContextBlock, ...] = ()
    dimensions: CellRange | None = None
    non_empty_cells: int = 0
    merged_ranges: tuple[CellRange, ...] = ()
    hidden: bool = False
    state: str = "visible"  # visible | hidden | veryHidden
    metadata: dict = field(default_factory=dict)

    @property
    def table_count(self) -> int:
        return len(self.tables)

    @property
    def row_count(self) -> int:
        return sum(t.row_count for t in self.tables)

    def table_by_name(self, name: str) -> TabularTable | None:
        wanted = name.strip().lower()
        for table in self.tables:
            if table.name.strip().lower() == wanted:
                return table
        return None


@dataclass(frozen=True, kw_only=True)
class TabularRelation:
    """Relación candidata entre columnas de tablas (no ejecutada en ingesta)."""

    id: UUID
    workbook_id: UUID
    from_table_id: UUID
    from_column_id: UUID
    to_table_id: UUID
    to_column_id: UUID
    kind: TabularRelationKind = TabularRelationKind.CANDIDATE_JOIN
    confidence: float = 0.0
    evidence: dict = field(default_factory=dict)
    provenance: CatalogProvenance = CatalogProvenance.INFERRED

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("TabularRelation.confidence must be within [0, 1]")


# ---------------------------------------------------------------------------
# Perfil y calidad
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TabularSheetProfile:
    """Perfil determinista de una hoja (sin LLM, sin cargar todo en RAM)."""

    name: str
    index: int
    row_count: int = 0
    column_count: int = 0
    non_empty_cells: int = 0
    used_range: CellRange | None = None
    merged_ranges: int = 0
    formulas: int = 0
    hidden_rows: int = 0
    hidden_columns: int = 0
    blank_row_separators: tuple[int, ...] = ()
    blank_column_separators: tuple[int, ...] = ()
    candidate_header_rows: tuple[int, ...] = ()
    candidate_tables: int = 0
    detected_tables: int = 0
    hidden: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TabularWorkbookProfile:
    """Perfil del workbook completo (brief §2): barato y determinista."""

    filename: str
    format: TabularFormat
    sheet_count: int = 0
    sheet_names: tuple[str, ...] = ()
    sheets: tuple[TabularSheetProfile, ...] = ()
    non_empty_cells: int = 0
    merged_cells: int = 0
    formulas: int = 0
    hidden_rows: int = 0
    hidden_columns: int = 0
    candidate_tables: int = 0
    truncated: bool = False
    limits_hit: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TabularQualityWarning:
    code: str
    message: str
    severity: TabularQualitySeverity = TabularQualitySeverity.WARNING
    sheet_name: str | None = None
    table_id: UUID | None = None
    physical_row: int | None = None
    column_name: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TabularQualityReport:
    """Reporte de calidad (brief §22): nunca bloquea la ingesta por sí mismo."""

    quality_score: float = 1.0
    warnings: tuple[TabularQualityWarning, ...] = ()
    metrics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.quality_score <= 1.0:
            raise ValueError("TabularQualityReport.quality_score must be within [0, 1]")

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


# ---------------------------------------------------------------------------
# Workbook (raíz)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class TabularWorkbook:
    """Representación canónica de un Excel/CSV: estructura completa.

    `content_hash` es el hash del archivo fuente (o del texto CSV normalizado)
    y gobierna la detección de cambios a nivel workbook. Cada tabla tiene su
    propio `schema_hash`/`content_hash` para updates incrementales.
    """

    id: UUID
    organization_id: UUID
    external_id: str
    filename: str
    format: TabularFormat
    content_hash: str
    sheets: tuple[TabularSheet, ...] = ()
    relations: tuple[TabularRelation, ...] = ()
    profile: TabularWorkbookProfile | None = None
    quality: TabularQualityReport | None = None
    workspace_id: UUID | None = None
    source_id: UUID | None = None
    language: str | None = None
    provenance: CatalogProvenance = CatalogProvenance.OBSERVED
    metadata: dict = field(default_factory=dict)

    def tables(self) -> tuple[TabularTable, ...]:
        return tuple(table for sheet in self.sheets for table in sheet.tables)

    def table_by_id(self, table_id: UUID) -> TabularTable | None:
        for table in self.tables():
            if table.id == table_id:
                return table
        return None

    def sheet_by_name(self, name: str) -> TabularSheet | None:
        wanted = name.strip().lower()
        for sheet in self.sheets:
            if sheet.name.strip().lower() == wanted:
                return sheet
        return None

    @property
    def sheet_count(self) -> int:
        return len(self.sheets)

    @property
    def sheet_names(self) -> tuple[str, ...]:
        return tuple(sheet.name for sheet in self.sheets)

    @property
    def table_count(self) -> int:
        return sum(len(sheet.tables) for sheet in self.sheets)

    @property
    def row_count(self) -> int:
        return sum(table.row_count for table in self.tables())

    def check_consistency(self) -> None:
        """Invariantes del árbol: ids/parents reales y columnas alineadas."""
        sheet_ids = {sheet.id for sheet in self.sheets}
        seen_table_ids: set[UUID] = set()
        for sheet in self.sheets:
            if sheet.workbook_id != self.id:
                raise TabularIntegrityError(
                    f"sheet {sheet.name!r} workbook_id {sheet.workbook_id} != {self.id}"
                )
            for table in sheet.tables:
                if table.workbook_id != self.id:
                    raise TabularIntegrityError(
                        f"table {table.name!r} workbook_id {table.workbook_id} != {self.id}"
                    )
                if table.sheet_id != sheet.id:
                    raise TabularIntegrityError(
                        f"table {table.name!r} sheet_id {table.sheet_id} != {sheet.id}"
                    )
                if table.id in seen_table_ids:
                    raise TabularIntegrityError(f"duplicate table id {table.id}")
                seen_table_ids.add(table.id)
                for row in table.rows:
                    if len(row.values) > len(table.columns):
                        raise TabularIntegrityError(
                            f"row {row.physical_row} of {table.name!r} exceeds column count"
                        )
        for relation in self.relations:
            if relation.workbook_id != self.id:
                raise TabularIntegrityError(
                    f"relation {relation.id} workbook_id != {self.id}"
                )
            if relation.from_table_id not in seen_table_ids:
                raise TabularIntegrityError(
                    f"relation {relation.id} references unknown from_table_id"
                )
            if relation.to_table_id not in seen_table_ids:
                raise TabularIntegrityError(
                    f"relation {relation.id} references unknown to_table_id"
                )
        for sheet in self.sheets:
            if sheet.id not in sheet_ids:  # pragma: no cover - defensive
                raise TabularIntegrityError(f"orphan sheet {sheet.id}")


class TabularIntegrityError(ValueError):
    """Violación de invariantes del árbol tabular."""


@dataclass(frozen=True, kw_only=True)
class TableFingerprint:
    """Estado persistido de una tabla (schema hash + row hashes)."""

    table_id: UUID
    schema_hash: str = ""
    row_hashes: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TabularFingerprint:
    """Estado persistido de un workbook para detectar cambios incrementales."""

    workbook_id: UUID
    content_hash: str | None = None
    pipeline_version: str = ""
    chunking_policy: str = ""
    materialization_policy: str = ""
    materialized_tables: list = field(default_factory=list)
    representations: dict = field(default_factory=dict)
    tables: dict[UUID, TableFingerprint] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TableDiff:
    """Diferencia de una tabla entre dos ingestas (fingerprinting §12)."""

    table_id: UUID
    change_kind: TabularChangeKind = TabularChangeKind.UNCHANGED
    schema_changed: bool = False
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    inserted_rows: tuple[int, ...] = ()
    updated_rows: tuple[int, ...] = ()
    deleted_rows: tuple[int, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def has_row_changes(self) -> bool:
        return bool(self.inserted or self.updated or self.deleted)

    @property
    def changed(self) -> bool:
        return (
            self.schema_changed
            or self.has_row_changes
            or self.change_kind is not TabularChangeKind.UNCHANGED
        )


@dataclass(frozen=True, kw_only=True)
class WorkbookDiff:
    """Cambios de un workbook completo en re-ingesta."""

    workbook_id: UUID
    change_kind: TabularChangeKind = TabularChangeKind.UNCHANGED
    table_diffs: tuple[TableDiff, ...] = ()
    deleted_table_ids: tuple[UUID, ...] = ()
    metadata: dict = field(default_factory=dict)

    @property
    def changed_table_ids(self) -> frozenset[UUID]:
        return frozenset(diff.table_id for diff in self.table_diffs if diff.changed)

    @property
    def unchanged_table_ids(self) -> frozenset[UUID]:
        return frozenset(diff.table_id for diff in self.table_diffs if not diff.changed)

    @property
    def row_stats(self) -> dict[str, int]:
        return {
            "inserted": sum(diff.inserted for diff in self.table_diffs),
            "updated": sum(diff.updated for diff in self.table_diffs),
            "deleted": sum(diff.deleted for diff in self.table_diffs),
            "unchanged": sum(diff.unchanged for diff in self.table_diffs),
        }


def _normalize_key(value: str) -> str:
    """Normaliza nombres para matching: minúsculas, sin acentos, snake_case."""
    import re
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")

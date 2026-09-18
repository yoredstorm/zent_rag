# =============================================================================
# Knowledge Tabular V2 — profiling, detección de tablas y headers
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.tabular import (
    TabularDetectionMethod,
    TabularSemanticType,
    TabularValueType,
)
from src.knowledge.tabular.builder import TabularBuildLimits, build_tabular_workbook
from src.knowledge.tabular.csv_reader import build_csv_workbook_grid
from src.knowledge.tabular.schema import infer_semantic_type
from src.knowledge.tabular.xlsx_reader import read_xlsx_grid
from tests import tabular_fixtures as fx

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_SOURCE = UUID("00000000-0000-0000-0000-0000000000bb")


def build(workbook_grid, filename: str, *, limits: TabularBuildLimits | None = None):
    return build_tabular_workbook(
        workbook_grid,
        organization_id=_ORG,
        external_id=f"obj/{filename}",
        source_id=_SOURCE,
        filename=filename,
        limits=limits,
    )


def xlsx(data: bytes, name: str, **kwargs):
    return build(read_xlsx_grid(data, name, **kwargs), name)


# ---------------------------------------------------------------------------
# ATPCO: el caso de aceptación §43
# ---------------------------------------------------------------------------


def test_atpco_header_not_first_row_table_infers_schema_and_semantics() -> None:
    workbook = xlsx(fx.atpco_workbook_bytes(), "ATPCO_TEST.xlsx")

    assert workbook.sheet_names == ("Record2",)
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.name == "ATPCO RECORD 2 RULES"
    assert table.range.min_row == 4 and table.range.max_row == 8
    assert table.header_rows == (4,)
    assert table.row_count == 4
    assert [column.original_name for column in table.columns] == [
        "Field Name",
        "Start Position",
        "End Position",
        "Length",
        "Description",
    ]
    assert [column.excel_letter for column in table.columns] == ["A", "B", "C", "D", "E"]

    by_name = {column.original_name: column for column in table.columns}
    assert by_name["Start Position"].inferred_type is TabularValueType.INTEGER
    assert by_name["Start Position"].semantic_type is TabularSemanticType.POSITION
    assert "position" in by_name["Start Position"].aliases
    assert by_name["Length"].semantic_type is TabularSemanticType.LENGTH
    assert by_name["Description"].semantic_type is TabularSemanticType.DESCRIPTION
    assert by_name["Field Name"].semantic_type is TabularSemanticType.NAME

    # Contexto conservado: título + subtítulo NO son header.
    context = {block.kind.value: block.text for block in table.context_blocks}
    assert context.get("title") == "ATPCO RECORD 2 RULES"
    assert context.get("subtitle") == "Field layout specification"

    # Valores exactos: '28' sigue siendo string crudo, la semántica es posicional.
    first = table.rows[0]
    assert first.physical_row == 5
    assert first.values == ("Carrier Code", "28", "29", "2", "Identifies carrier")
    assert first.mapping(table.columns)["start_position"] == "28"

    # Perfil: fila 3 es separadora, header candidato = fila 4.
    assert workbook.profile is not None
    sheet_profile = workbook.profile.sheets[0]
    assert sheet_profile.candidate_header_rows == (4,)
    assert 3 in sheet_profile.blank_row_separators
    assert workbook.quality is not None and workbook.quality.quality_score >= 0.9


def test_atpco_positions_are_not_confused_with_physical_columns() -> None:
    """B35 = 28: la posición física de la celda no es el start_position."""
    workbook = xlsx(fx.atpco_workbook_bytes(), "ATPCO_TEST.xlsx")
    table = workbook.tables()[0]
    column = table.column_by_name("start_position")
    assert column is not None
    assert column.physical_column == 2  # columna física B
    assert column.physical_index == 1
    assert column.excel_letter == "B"
    assert table.rows[0].value_for(column) == "28"  # valor de dominio
    assert table.metadata["column_letters"] == ["A", "B", "C", "D", "E"]


def test_multi_sheet_and_multiple_tables_per_sheet() -> None:
    workbook = xlsx(fx.multi_sheet_workbook_bytes(), "multi.xlsx")
    assert workbook.sheet_count == 2
    assert workbook.table_count == 2
    assert workbook.tables()[0].name.startswith("Rules")
    carriers = workbook.sheets[1].tables[0]
    assert carriers.row_count == 2
    assert carriers.columns[0].semantic_type is TabularSemanticType.CODE
    assert carriers.columns[0].inferred_type is TabularValueType.CODE


def test_header_not_first_row_keeps_title_as_context() -> None:
    workbook = xlsx(fx.header_not_first_row_workbook_bytes(), "hdr.xlsx")
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.name == "Reporte de posiciones"
    assert table.header_rows == (5,)
    assert table.range.min_row == 5
    assert any(block.kind.value == "subtitle" for block in table.context_blocks)


def test_multi_header_builds_header_path() -> None:
    workbook = xlsx(fx.multi_header_workbook_bytes(), "multiheader.xlsx")
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.header_rows == (3, 4)
    assert table.header_depth == 2
    by_name = {column.original_name: column for column in table.columns}
    assert by_name["Start"].header_path == ("Position", "Start")
    assert by_name["End"].header_path == ("Position", "End")
    assert by_name["Field Name"].header_path == ("Field Name",)


def test_merged_title_is_context_not_table() -> None:
    workbook = xlsx(fx.merged_headers_workbook_bytes(), "merged.xlsx")
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.name == "FIELD DEFINITION"
    assert [column.original_name for column in table.columns] == [
        "Field Name",
        "Position",
        "Length",
    ]


def test_multiple_tables_same_sheet_split_by_blank_rows() -> None:
    workbook = xlsx(fx.multiple_tables_sheet_bytes(), "multitable.xlsx")
    assert workbook.table_count == 2
    names = [table.name for table in workbook.tables()]
    assert names == ["TABLE A: Field definitions", "TABLE B: Category mappings"]
    second = workbook.tables()[1]
    assert second.range.min_row == 7
    assert second.columns[0].original_name == "Category"


def test_dates_formulas_and_no_evaluation() -> None:
    workbook = xlsx(fx.dates_and_formulas_workbook_bytes(), "dates.xlsx")
    table = workbook.tables()[0]
    by_name = {column.original_name: column for column in table.columns}
    assert by_name["Valid From"].semantic_type is TabularSemanticType.DATE
    assert by_name["Price"].inferred_type is TabularValueType.FLOAT
    # Fórmula capturada sin evaluar; el valor cacheado puede estar vacío.
    details = {detail.address: detail for detail in table.rows[0].cell_details}
    assert details["D2"].formula == "=C2*2"
    assert table.rows[0].value_for(by_name["Total"]) == ""


def test_conditional_semantics_for_real_headers() -> None:
    """Reglas por nombre + tipo: cubren headers reales sin falsos positivos."""
    # Data Row / Std # / Item Row No. con enteros → identificadores de fila.
    for header in ("Data Row", "Std #", "Item Row No."):
        semantic, _, _ = infer_semantic_type(
            header, value_type=TabularValueType.INTEGER
        )
        assert semantic is TabularSemanticType.IDENTIFIER, header

    # Location con enteros es posición de bytes; con texto es referencia.
    semantic, _, _ = infer_semantic_type(
        "Location", value_type=TabularValueType.INTEGER
    )
    assert semantic is TabularSemanticType.POSITION
    semantic, _, _ = infer_semantic_type(
        "Location", value_type=TabularValueType.STRING
    )
    assert semantic is TabularSemanticType.REFERENCE

    # Required solo es booleano si sus valores lo son.
    semantic, _, _ = infer_semantic_type(
        "Required", value_type=TabularValueType.BOOLEAN
    )
    assert semantic is TabularSemanticType.BOOLEAN
    semantic, _, _ = infer_semantic_type(
        "Required", value_type=TabularValueType.STRING, max_length=200
    )
    assert semantic is not TabularSemanticType.BOOLEAN

    semantic, _, _ = infer_semantic_type(
        "Business Area", value_type=TabularValueType.STRING
    )
    assert semantic is TabularSemanticType.CATEGORY


def test_codes_are_preserved_exactly() -> None:
    workbook = xlsx(fx.codes_workbook_bytes(), "codes.xlsx")
    table = workbook.tables()[0]
    values = {row.values[0] for row in table.rows}
    assert values == {"CAT10", "CAT 14", "TARNO"}
    all_values = {value for row in table.rows for value in row.values}
    assert "R&&&&&E&" in all_values
    assert "YQYR" in all_values
    assert "R2" in all_values


def test_hidden_rows_reported_in_quality() -> None:
    workbook = xlsx(fx.hidden_rows_workbook_bytes(), "hidden.xlsx")
    table = workbook.tables()[0]
    assert 3 in table.metadata["hidden_rows"]
    codes = {warning.code for warning in workbook.quality.warnings}
    assert "hidden_data" in codes


def test_excel_formal_table_has_priority() -> None:
    workbook = xlsx(fx.excel_table_workbook_bytes(), "formal.xlsx")
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.detection_method is TabularDetectionMethod.EXCEL_TABLE
    assert table.name == "ZoneTable"
    assert table.header_rows == (1,)
    assert [column.original_name for column in table.columns] == ["Zone", "Code"]
    assert table.row_count == 2


def test_duplicate_headers_do_not_kill_detection() -> None:
    """Caso real ATPCO Attributes: header con columna homónima.

    Antes: la heurística exigía headers únicos y descartaba la tabla completa
    (0 tablas, 0 filas). Ahora: la tabla se detecta y las columnas homónimas se
    indexan con sufijo interno conservando el valor raw.
    """
    workbook = xlsx(fx.duplicate_headers_workbook_bytes(), "ATPCO_Attributes.xlsx")
    assert workbook.table_count == 1
    table = workbook.tables()[0]
    assert table.header_rows == (1,)
    assert table.row_count == 3
    assert [column.original_name for column in table.columns][:2] == [
        "Data Row",
        "Std #",
    ]
    normalized = [column.normalized_name for column in table.columns]
    assert normalized[0] == "data_row"
    assert normalized[-1] == "data_row_2"
    assert len(set(normalized)) == len(normalized)

    first_row = table.rows[0]
    assert first_row.mapping(table.columns)["data_row"] == "24"
    assert first_row.mapping(table.columns)["data_row_2"] == "24"
    assert table.columns[-1].metadata["deduplicated_name"] is True

    codes = {warning.code for warning in workbook.quality.warnings}
    assert "duplicate_headers" in codes


def test_large_workbook_respects_limits_and_streams() -> None:
    grid = read_xlsx_grid(
        fx.large_workbook_bytes(500),
        "large.xlsx",
        max_rows_per_sheet=100,
        max_cells=100_000,
    )
    assert grid.sheets[0].column_count == 3
    assert grid.truncated is True
    assert "max_rows_per_sheet" in grid.limits_hit

    workbook = build(grid, "large.xlsx")
    table = workbook.tables()[0]
    assert table.row_count == 99  # 100 filas leídas incluyendo el header
    assert workbook.profile is not None and workbook.profile.truncated


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_csv_simple_and_dialects() -> None:
    grid, dialect = build_csv_workbook_grid(fx.simple_csv_bytes(), "simple.csv")
    assert dialect.delimiter == ","
    workbook = build(grid, "simple.csv")
    table = workbook.tables()[0]
    assert table.row_count == 2
    assert table.columns[1].original_name == "Start Position"
    assert table.columns[1].inferred_type is TabularValueType.INTEGER

    grid_semi, dialect_semi = build_csv_workbook_grid(fx.semicolon_csv_bytes(), "semi.csv")
    assert dialect_semi.delimiter == ";"
    workbook_semi = build(grid_semi, "semi.csv")
    assert workbook_semi.tables()[0].row_count == 2

    grid_bom, dialect_bom = build_csv_workbook_grid(fx.utf8_bom_csv_bytes(), "bom.csv")
    assert dialect_bom.has_bom is True
    workbook_bom = build(grid_bom, "bom.csv")
    assert workbook_bom.tables()[0].columns[0].original_name == "Field Name"

    grid_latin, dialect_latin = build_csv_workbook_grid(fx.latin1_csv_bytes(), "latin.csv")
    assert dialect_latin.encoding in ("cp1252", "latin-1")
    assert dialect_latin.decimal_style == "comma"
    workbook_latin = build(grid_latin, "latin.csv")
    assert workbook_latin.tables()[0].columns[0].original_name == "Código"


def test_csv_quoted_fields_and_ragged_rows() -> None:
    grid, _ = build_csv_workbook_grid(fx.quoted_csv_bytes(), "quoted.csv")
    workbook = build(grid, "quoted.csv")
    table = workbook.tables()[0]
    assert table.rows[0].values[0] == "Carrier, Code"
    assert table.rows[0].values[1] == "Identifies carrier, primary"

    grid_ragged, _ = build_csv_workbook_grid(fx.ragged_csv_bytes(), "ragged.csv")
    workbook_ragged = build(grid_ragged, "ragged.csv")
    codes = {warning.code for warning in workbook_ragged.quality.warnings}
    assert "empty_headers" in codes


def test_quality_report_does_not_block_ingestion() -> None:
    workbook = xlsx(fx.atpco_workbook_bytes(), "ATPCO_TEST.xlsx")
    assert workbook.quality is not None
    assert 0.0 < workbook.quality.quality_score <= 1.0
    for warning in workbook.quality.warnings:
        assert warning.message

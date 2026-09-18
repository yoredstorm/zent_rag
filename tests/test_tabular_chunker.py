# =============================================================================
# Knowledge Tabular V2 — TabularChunker multinivel + point keys deterministas
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.domain.knowledge_v2 import ChunkType
from src.knowledge.structure import get_parser
from src.knowledge.tabular.chunker import (
    TabularChunkingConfig,
    chunk_tabular_workbook,
)
from src.knowledge.tabular.ids import point_id_for
from tests import tabular_fixtures as fx

_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_SOURCE = UUID("00000000-0000-0000-0000-0000000000bb")
_EXTERNAL = "obj/ATPCO_TEST.xlsx"


def build_document():
    parser = get_parser("xlsx")
    return parser.parse(
        fx.atpco_workbook_bytes(),
        organization_id=_ORG,
        external_id=_EXTERNAL,
        source_id=_SOURCE,
        source_name="ATPCO_TEST.xlsx",
    )


def chunks_by_level(chunks):
    levels: dict[int, list] = {}
    for chunk in chunks:
        levels.setdefault(int(chunk.metadata["level"]), []).append(chunk)
    return levels


def test_chunker_emits_all_levels_with_metadata() -> None:
    document = build_document()
    chunks = chunk_tabular_workbook(document, config=TabularChunkingConfig(row_group_size=2))
    levels = chunks_by_level(chunks)

    assert set(levels) == {0, 1, 2, 3, 4}
    assert levels[0][0].metadata["knowledge_type"] == "table_workbook"
    assert levels[1][0].metadata["knowledge_type"] == "table_sheet"
    assert levels[2][0].metadata["knowledge_type"] == "table_schema"
    assert levels[3][0].metadata["knowledge_type"] == "table_row_group"
    assert levels[4][0].metadata["knowledge_type"] == "table_row"

    # Tabla/fila/hoja presentes en cada chunk de fila (jerarquía explícita).
    row_chunk = levels[4][0]
    metadata = row_chunk.metadata
    assert metadata["table_name"] == "ATPCO RECORD 2 RULES"
    assert metadata["sheet"] == "Record2"
    assert metadata["workbook"] == "ATPCO_TEST.xlsx"
    assert metadata["physical_row"] == 5
    assert metadata["header_row"] == 4
    assert metadata["columns"][:2] == ["field_name", "start_position"]
    assert metadata["values"]["start_position"] == "28"
    assert metadata["format"] == "xlsx"
    assert metadata["v2_tabular"] == "true"

    # Nunca una fila sin sus encabezados.
    assert "Start Position: 28" in row_chunk.content
    assert "Field Name: Carrier Code" in row_chunk.content
    assert "Workbook: ATPCO_TEST.xlsx" in row_chunk.content


def test_parent_chain_uses_deterministic_point_ids() -> None:
    document = build_document()
    chunks = chunk_tabular_workbook(document, config=TabularChunkingConfig(row_group_size=2))
    levels = chunks_by_level(chunks)

    schema_key = levels[2][0].metadata["point_key"]
    sheet_key = levels[1][0].metadata["point_key"]
    workbook_key = levels[0][0].metadata["point_key"]

    assert levels[2][0].metadata["parent_id"] == str(point_id_for(sheet_key))
    assert levels[1][0].metadata["parent_id"] == str(point_id_for(workbook_key))
    assert levels[0][0].metadata["parent_id"] is None
    # El schema_id del row group apunta al schema (útil para expandir contexto).
    assert levels[3][0].metadata["schema_id"] == str(point_id_for(schema_key))
    assert levels[3][0].metadata["parent_id"] == str(point_id_for(schema_key))
    assert levels[4][0].metadata["parent_id"] == str(point_id_for(schema_key))


def test_point_keys_are_stable_across_runs() -> None:
    config = TabularChunkingConfig(row_group_size=2)
    first = chunk_tabular_workbook(build_document(), config=config)
    second = chunk_tabular_workbook(build_document(), config=config)
    first_keys = [chunk.metadata["point_key"] for chunk in first]
    second_keys = [chunk.metadata["point_key"] for chunk in second]
    assert first_keys == second_keys
    assert len(set(first_keys)) == len(first_keys)


def test_chunk_types_mark_parents_and_candidates() -> None:
    chunks = chunk_tabular_workbook(
        build_document(), config=TabularChunkingConfig(row_group_size=2)
    )
    for chunk in chunks:
        level = int(chunk.metadata["level"])
        if level <= 2:
            assert chunk.chunk_type is ChunkType.DOCUMENT_STRUCTURE
        else:
            assert chunk.chunk_type is ChunkType.TABLE_AWARE


def test_changed_table_filter_skips_unchanged_tables() -> None:
    document = build_document()
    table = document.tabular.tables()[0]
    chunks = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(row_group_size=2),
        changed_table_ids=frozenset({table.id}),
    )
    levels = chunks_by_level(chunks)
    assert set(levels) == {0, 1, 2, 3, 4}  # resúmenes + schema + filas cambiadas

    chunks_none = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(row_group_size=2),
        changed_table_ids=frozenset(),
    )
    levels_none = chunks_by_level(chunks_none)
    assert set(levels_none) == {0, 1, 2}  # solo resúmenes/schema


def test_max_embedding_rows_caps_row_chunks() -> None:
    document = build_document()
    chunks = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(row_group_size=2, max_embedding_rows_per_table=2),
    )
    levels = chunks_by_level(chunks)
    assert len(levels[4]) == 2
    assert [chunk.metadata["physical_row"] for chunk in levels[4]] == [5, 6]


def test_cell_level_is_opt_in_and_cites_address() -> None:
    document = build_document()
    without = chunk_tabular_workbook(document, config=TabularChunkingConfig())
    assert all(int(chunk.metadata["level"]) != 5 for chunk in without)

    with_cells = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(include_cells=True, max_cell_chunks_per_table=5),
    )
    cells = [chunk for chunk in with_cells if int(chunk.metadata["level"]) == 5]
    assert 1 <= len(cells) <= 5
    first = cells[0]
    assert first.metadata["cell_address"].startswith(("B", "C", "D"))
    assert "= " in first.content
    assert first.metadata["knowledge_type"] == "table_cell"


# ---------------------------------------------------------------------------
# F1 — cobertura total de filas + formato compacto + columnas clave
# ---------------------------------------------------------------------------


def build_large_document(rows: int = 300):
    parser = get_parser("xlsx")
    return parser.parse(
        fx.large_workbook_bytes(rows),
        organization_id=_ORG,
        external_id="obj/large.xlsx",
        source_id=_SOURCE,
        source_name="large.xlsx",
    )


def test_row_groups_cover_far_beyond_embedding_row_cap() -> None:
    """Los row-groups cubren TODAS las filas aunque las filas individuales estén capadas."""
    document = build_large_document(300)
    table = document.tabular.tables()[0]
    last_row = table.rows[-1].physical_row
    chunks = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(
            row_group_size=20,
            max_embedding_rows_per_table=25,
            max_group_rows=10_000,
        ),
    )
    levels = chunks_by_level(chunks)
    assert len(levels[4]) == 25  # filas individuales capadas
    group_end_rows = [chunk.metadata["row_end"] for chunk in levels[3]]
    assert max(group_end_rows) == last_row
    assert len(group_end_rows) > 5


def test_row_group_compact_format_has_headers_and_positional_rows() -> None:
    document = build_document()
    chunks = chunk_tabular_workbook(
        document, config=TabularChunkingConfig(row_group_size=10)
    )
    group = chunks_by_level(chunks)[3][0]
    content = group.content
    assert content.startswith("TABLE: ATPCO RECORD 2 RULES | SHEET: Record2 | ROWS:")
    assert "KEY: Field Name | Start Position | End Position | Length | Description" in content
    assert "5: Carrier Code | 28 | 29 | 2 | Identifies carrier" in content
    # Tabla angosta (5 columnas): sin nota de columnas clave.
    assert "NOTE: key columns shown" not in content


def test_wide_tables_render_only_key_columns_in_groups() -> None:
    from uuid import uuid4

    from src.core.domain.tabular import (
        CellRange,
        TabularColumn,
        TabularFormat,
        TabularRow,
        TabularSemanticType,
        TabularSheet,
        TabularTable,
        TabularValueType,
        TabularWorkbook,
    )
    from src.knowledge.tabular.document import document_id_for, tabular_document
    from src.knowledge.tabular.ids import TABULAR_NS

    workbook_id = uuid4()
    sheet_id = uuid4()
    columns = []
    for index in range(16):
        semantic = (
            TabularSemanticType.NAME
            if index == 0
            else TabularSemanticType.DESCRIPTION
            if index == 1
            else TabularSemanticType.UNKNOWN
        )
        columns.append(
            TabularColumn(
                id=uuid4(),
                physical_index=index,
                physical_column=index + 1,
                excel_letter=chr(ord("A") + index),
                original_name=f"Col {index}",
                normalized_name=f"col_{index}",
                inferred_type=TabularValueType.STRING,
                semantic_type=semantic,
            )
        )
    rows = tuple(
        TabularRow(
            physical_row=index + 2,
            logical_index=index,
            values=tuple(f"v{index}-{column_index}" for column_index in range(16)),
        )
        for index in range(40)
    )
    table = TabularTable(
        id=uuid4(),
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        name="Wide",
        range=CellRange(min_row=1, max_row=41, min_col=1, max_col=16),
        columns=tuple(columns),
        rows=rows,
        header_rows=(1,),
    )
    workbook = TabularWorkbook(
        id=workbook_id,
        organization_id=_ORG,
        external_id="obj/wide.xlsx",
        filename="wide.xlsx",
        format=TabularFormat.XLSX,
        content_hash="b" * 64,
        sheets=(
            TabularSheet(
                id=sheet_id, workbook_id=workbook_id, name="W", index=0, tables=(table,)
            ),
        ),
    )
    document = tabular_document(
        workbook,
        document_id=document_id_for(TABULAR_NS, _ORG, _SOURCE, "obj/wide.xlsx"),
    )
    chunks = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(row_group_size=10, max_group_key_columns=2),
    )
    group = chunks_by_level(chunks)[3][0]
    assert "NOTE: key columns shown" in group.content
    assert "KEY: Col 0 | Col 2" in group.content
    # Primera línea de fila: solo las columnas clave (nombre + columna corta).
    row_line = group.content.splitlines()[3]
    assert row_line.startswith("2: v0-0 | v0-2")
    assert "v0-1" not in row_line


def test_row_group_sanitizes_header_newlines() -> None:
    """Un header con salto de línea (Rec\nLay\nout) no rompe las líneas del grupo."""
    from uuid import uuid4

    from src.core.domain.tabular import (
        CellRange,
        TabularColumn,
        TabularFormat,
        TabularRow,
        TabularSheet,
        TabularTable,
        TabularValueType,
        TabularWorkbook,
    )
    from src.knowledge.tabular.document import document_id_for, tabular_document
    from src.knowledge.tabular.ids import TABULAR_NS

    workbook_id = uuid4()
    sheet_id = uuid4()
    column = TabularColumn(
        id=uuid4(),
        physical_index=0,
        physical_column=1,
        excel_letter="A",
        original_name="Rec\nLay\nout",
        normalized_name="rec_lay_out",
        inferred_type=TabularValueType.STRING,
    )
    rows = tuple(
        TabularRow(physical_row=index + 2, logical_index=index, values=("L",))
        for index in range(4)
    )
    table = TabularTable(
        id=uuid4(),
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        name="Registro\nLargo",
        range=CellRange(min_row=1, max_row=6, min_col=1, max_col=1),
        columns=(column,),
        rows=rows,
        header_rows=(1,),
    )
    workbook = TabularWorkbook(
        id=workbook_id,
        organization_id=_ORG,
        external_id="obj/nl.xlsx",
        filename="nl.xlsx",
        format=TabularFormat.XLSX,
        content_hash="c" * 64,
        sheets=(
            TabularSheet(
                id=sheet_id, workbook_id=workbook_id, name="Hoja\nUno", index=0, tables=(table,)
            ),
        ),
    )
    document = tabular_document(
        workbook, document_id=document_id_for(TABULAR_NS, _ORG, _SOURCE, "obj/nl.xlsx")
    )
    chunks = chunk_tabular_workbook(
        document, config=TabularChunkingConfig(row_group_size=4)
    )
    group = chunks_by_level(chunks)[3][0]
    lines = group.content.splitlines()
    assert lines[0].startswith("TABLE: Registro Largo | SHEET: Hoja Uno | ROWS:")
    assert lines[1] == "KEY: Rec Lay out"
    assert all("\n" not in line for line in lines)

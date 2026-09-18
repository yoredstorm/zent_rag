# =============================================================================
# Knowledge Tabular V2 — materialización opcional en Managed Database
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.knowledge.tabular.builder import build_tabular_workbook
from src.knowledge.tabular.managed_materializer import (
    PROVENANCE_COLUMNS,
    insert_rows_sql,
    materialize_table,
    table_proposal,
)
from src.knowledge.tabular.xlsx_reader import read_xlsx_grid
from tests import tabular_fixtures as fx


def build_table():
    workbook = build_tabular_workbook(
        read_xlsx_grid(fx.atpco_workbook_bytes(), "ATPCO_TEST.xlsx"),
        organization_id=uuid4(),
        external_id="obj/ATPCO_TEST.xlsx",
        source_id=uuid4(),
        filename="ATPCO_TEST.xlsx",
    )
    return workbook, workbook.tables()[0]


def test_table_proposal_maps_types_and_appends_provenance() -> None:
    _workbook, table = build_table()
    proposal = table_proposal(table)
    assert len(proposal["tables"]) == 1
    entry = proposal["tables"][0]
    assert entry["name"].startswith("zent_")
    fields = {field["name"]: field for field in entry["fields"]}

    assert fields["start_position"]["type"] == "Integer"
    assert fields["length"]["type"] == "Integer"
    assert fields["field_name"]["type"] == "Text"
    assert fields["description"]["type"] == "Text"
    for column in PROVENANCE_COLUMNS:
        assert column in fields
    # Field Name es NAME (no identificador): no se fuerza unique.
    assert fields["field_name"]["unique"] is False


def test_table_proposal_marks_unique_code_columns() -> None:
    workbook = build_tabular_workbook(
        read_xlsx_grid(fx.multi_sheet_workbook_bytes(), "multi.xlsx"),
        organization_id=uuid4(),
        external_id="obj/multi.xlsx",
        source_id=uuid4(),
        filename="multi.xlsx",
    )
    carriers = workbook.sheets[1].tables[0]
    proposal = table_proposal(carriers)
    fields = {field["name"]: field for field in proposal["tables"][0]["fields"]}
    assert fields["carrier_code"]["unique"] is True


def test_insert_rows_sql_escapes_and_preserves_values() -> None:
    _workbook, table = build_table()
    proposal = table_proposal(table)
    columns = proposal["tables"][0]["fields"][: len(table.columns)]
    rows = [tuple(row.values) for row in table.rows]
    sql = insert_rows_sql(
        proposal["tables"][0]["name"],
        columns,
        rows,
        source_id="source-1",
        workbook="ATPCO_TEST.xlsx",
        sheet="Record2",
        table_id=str(table.id),
        physical_rows=[row.physical_row for row in table.rows],
    )
    assert "INSERT INTO" in sql
    assert "'source-1'" in sql
    assert "'ATPCO_TEST.xlsx'" in sql
    assert "'Record2'" in sql
    assert "'Carrier Code'" in sql
    # start_position numérico sin comillas; length idem.
    assert ", 28, 29, 2, 'Identifies carrier'" in sql

    # Valores con comillas se escapan ('' ) y vacíos → NULL.
    escaped = insert_rows_sql(
        "zent_test",
        columns[:1],
        [("O'Hara",), ("",)],
        source_id="s",
        workbook="w",
        sheet="sh",
        table_id="t",
        physical_rows=[1, 2],
    )
    assert "'O''Hara'" in escaped
    assert "NULL" in escaped


@pytest.mark.asyncio
async def test_materialize_table_skips_without_managed_database() -> None:
    _workbook, table = build_table()
    result = await materialize_table(
        table,
        organization_id=uuid4(),
        workspace_id=UUID("00000000-0000-0000-0000-00000000dead"),
        workbook_name="ATPCO_TEST.xlsx",
        sheet_name="Record2",
        source_id=uuid4(),
    )
    assert result.status == "skipped"


# ---------------------------------------------------------------------------
# CSV: materialización con TODAS las columnas y nombre SQL limpio
# ---------------------------------------------------------------------------


def build_csv_table():
    from src.knowledge.tabular.csv_reader import build_csv_workbook_grid

    grid, _dialect = build_csv_workbook_grid(fx.simple_csv_bytes(), "simple.csv")
    workbook = build_tabular_workbook(
        grid,
        organization_id=uuid4(),
        external_id="obj/simple.csv",
        source_id=uuid4(),
        filename="simple.csv",
    )
    return workbook, workbook.tables()[0]


def test_base_table_name_strips_range_suffix() -> None:
    from src.knowledge.tabular.managed_materializer import base_table_name

    _workbook, csv_table = build_csv_table()
    # "simple table 1:1-3" → "simple"
    assert base_table_name(csv_table) == "simple"

    class _Stub:
        name = "ATPCO_Attributes table 1:1-24"

    assert base_table_name(_Stub()) == "ATPCO_Attributes"

    class _StubTwo:
        name = "Ventas table 1:1-3:8"

    assert base_table_name(_StubTwo()) == "Ventas"

    class _StubPlain:
        name = "ATPCO RECORD 2 RULES"

    assert base_table_name(_StubPlain()) == "ATPCO RECORD 2 RULES"


def test_csv_proposal_materializes_all_columns_and_rows() -> None:
    _workbook, table = build_csv_table()
    proposal = table_proposal(table)
    entry = proposal["tables"][0]
    assert entry["name"] == "zent_simple"
    field_names = [field["name"] for field in entry["fields"]]
    for column in ("field_name", "start_position", "length"):
        assert column in field_names
    for provenance in PROVENANCE_COLUMNS:
        assert provenance in field_names

    sql = insert_rows_sql(
        entry["name"],
        entry["fields"][: len(table.columns)],
        [tuple(row.values) for row in table.rows],
        source_id="src-csv",
        workbook="simple.csv",
        sheet="simple",
        table_id=str(table.id),
        physical_rows=[row.physical_row for row in table.rows],
    )
    assert "'Carrier Code', 28, 2" in sql
    assert "'Tariff Number', 30, 3" in sql
    assert "'simple.csv'" in sql

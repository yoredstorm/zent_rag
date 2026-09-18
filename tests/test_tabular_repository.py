# =============================================================================
# Knowledge Tabular V2 — repositorio Postgres + persistencia incremental
# =============================================================================
# Repos reales (Postgres) para tabular_workbooks/sheets/tables/columns/rows.
# Verifica aislamiento por organización y diffs incrementales (insert/update/
# delete/schema), no solo el happy path.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.tabular import TabularChangeKind
from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.tabular import PostgresTabularRepository
from src.knowledge.tabular.builder import build_tabular_workbook
from src.knowledge.tabular.persistence import persist_tabular_workbook
from src.knowledge.tabular.xlsx_reader import read_xlsx_grid
from tests import tabular_fixtures as fx


def make_workbook(organization_id, source_id, *, rows=None):
    data = fx.atpco_workbook_bytes()
    grid = read_xlsx_grid(data, "ATPCO_TEST.xlsx")
    workbook = build_tabular_workbook(
        grid,
        organization_id=organization_id,
        external_id="obj/ATPCO_TEST.xlsx",
        source_id=source_id,
        filename="ATPCO_TEST.xlsx",
    )
    if rows is None:
        return workbook
    # Reconstruye un workbook con filas modificadas conservando ids estables.
    from dataclasses import replace


    table = workbook.tables()[0]
    new_rows = []
    for index, override in enumerate(rows):
        base = table.rows[index]
        cells = tuple(str(value) for value in override)
        if cells == base.values:
            new_rows.append(base)
            continue
        new_rows.append(
            replace(
                base,
                values=cells,
                content_hash=f"custom-{index}-" + ",".join(cells),
            )
        )
    new_table = replace(table, rows=tuple(new_rows), content_hash="custom-content")
    sheet = replace(workbook.sheets[0], tables=(new_table,))
    return replace(workbook, sheets=(sheet,))


@pytest.fixture
async def context():
    org_repo = PostgresOrganizationRepository()
    organization = await org_repo.create_organization(
        uuid4(), f"Tabular Org {uuid4().hex[:6]}"
    )
    other = await org_repo.create_organization(
        uuid4(), f"Tabular Other {uuid4().hex[:6]}"
    )
    return {"organization": organization, "other": other, "source_id": uuid4()}


async def test_upsert_workbook_persists_full_tree_and_fingerprint(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])

    diff = await persist_tabular_workbook(repo, workbook)
    assert diff.change_kind is TabularChangeKind.CREATED
    assert len(diff.changed_table_ids) == 1
    assert diff.row_stats["inserted"] == 4

    fingerprint = await repo.get_fingerprint(context["organization"].id, workbook.id)
    assert fingerprint is not None
    assert fingerprint.content_hash == workbook.content_hash
    table = workbook.tables()[0]
    assert table.id in fingerprint.tables
    assert len(fingerprint.tables[table.id].row_hashes) == 4

    metadata = await repo.get_workbook(
        context["organization"].id, context["source_id"], "obj/ATPCO_TEST.xlsx"
    )
    assert metadata is not None
    assert metadata["table_count"] == 1
    assert metadata["row_count"] == 4
    assert metadata["profile"]["candidate_tables"] == 1
    assert metadata["quality"]["quality_score"] > 0

    stored_table = await repo.get_table(context["organization"].id, table.id)
    assert stored_table is not None
    assert stored_table["name"] == "ATPCO RECORD 2 RULES"
    columns = stored_table["columns"]
    assert [column["normalized_name"] for column in columns][:2] == [
        "field_name",
        "start_position",
    ]
    start_position = columns[1]
    assert start_position["semantic_type"] == "position"
    assert start_position["inferred_type"] == "integer"
    assert "position" in start_position["aliases"]

    rows = await repo.fetch_rows(context["organization"].id, table.id)
    assert len(rows) == 4
    first = rows[0]
    assert first["physical_row"] == 5
    assert first["values"]["field_name"] == "Carrier Code"
    assert first["values"]["start_position"] == "28"


async def test_repository_tenant_isolation(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    await persist_tabular_workbook(repo, workbook)
    table = workbook.tables()[0]

    assert await repo.get_table(context["other"].id, table.id) is None
    assert await repo.fetch_rows(context["other"].id, table.id) == []
    assert await repo.list_tables(context["other"].id) == []
    assert (
        await repo.get_workbook(
            context["other"].id, context["source_id"], "obj/ATPCO_TEST.xlsx"
        )
        is None
    )

    sample = await repo.sample_values(
        context["organization"].id, table.id, table.columns[1].id, limit=5
    )
    assert sample == ["28", "30", "33", "36"]
    assert await repo.sample_values(context["other"].id, table.id, table.columns[1].id) == []


async def test_incremental_update_detects_only_the_changed_row(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    first_diff = await persist_tabular_workbook(repo, workbook)
    assert first_diff.change_kind is TabularChangeKind.CREATED

    table = workbook.tables()[0]
    modified = make_workbook(
        context["organization"].id,
        context["source_id"],
        rows=[
            ("Carrier Code", "28", "29", "2", "Identifies carrier"),
            ("Tariff Number", "30", "32", "4", "Identifies tariff"),  # length cambiado
            ("Rule Number", "33", "35", "3", "Identifies rule"),
            ("Fare Class", "36", "43", "8", "Fare class code"),
        ],
    )
    modified_table = modified.tables()[0]
    assert modified_table.id == table.id
    assert modified.content_hash == workbook.content_hash  # el archivo no cambió

    diff = await persist_tabular_workbook(repo, modified)
    assert diff.change_kind is TabularChangeKind.UPDATED
    assert diff.row_stats["updated"] == 1
    assert diff.row_stats["inserted"] == 0
    assert diff.row_stats["deleted"] == 0
    assert diff.row_stats["unchanged"] == 3
    assert diff.changed_table_ids == frozenset({table.id})

    rows = await repo.fetch_rows(context["organization"].id, table.id)
    values = {row["physical_row"]: row["values"] for row in rows}
    assert values[6]["length"] == "4"
    assert values[5]["length"] == "2"


async def test_row_deletion_and_table_removal(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    await persist_tabular_workbook(repo, workbook)
    table = workbook.tables()[0]

    from dataclasses import replace

    reduced_table = replace(table, rows=table.rows[:2], content_hash="reduced")
    sheet = replace(workbook.sheets[0], tables=(reduced_table,))
    reduced = replace(workbook, sheets=(sheet,))

    diff = await persist_tabular_workbook(repo, reduced)
    assert diff.row_stats["deleted"] == 2
    rows = await repo.fetch_rows(context["organization"].id, table.id)
    assert [row["physical_row"] for row in rows] == [5, 6]

    # Sin tablas → deleted_table_ids y cascade.
    empty_sheet = replace(workbook.sheets[0], tables=())
    empty = replace(workbook, sheets=(empty_sheet,))
    diff = await persist_tabular_workbook(repo, empty)
    assert diff.deleted_table_ids == (table.id,)
    assert await repo.get_table(context["organization"].id, table.id) is None
    assert await repo.fetch_rows(context["organization"].id, table.id) == []


async def test_schema_change_is_detected(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    await persist_tabular_workbook(repo, workbook)

    from dataclasses import replace

    table = workbook.tables()[0]
    new_column = replace(
        table.columns[1],
        original_name="Start Byte",
        normalized_name="start_byte",
        semantic_type=table.columns[1].semantic_type,
    )
    renamed = replace(
        table,
        columns=(table.columns[0], new_column, *table.columns[2:]),
        schema_hash="schema-v2",
    )
    sheet = replace(workbook.sheets[0], tables=(renamed,))
    updated = replace(workbook, sheets=(sheet,))

    diff = await persist_tabular_workbook(repo, updated)
    assert diff.change_kind is TabularChangeKind.UPDATED
    assert any(table_diff.schema_changed for table_diff in diff.table_diffs)
    stored = await repo.get_table(context["organization"].id, table.id)
    assert stored["columns"][1]["normalized_name"] == "start_byte"


async def test_interrupted_semantic_index_is_recovered(context) -> None:
    """Si falta representations.semantic, el re-sync reindexa aunque no cambie."""
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    first = await persist_tabular_workbook(repo, workbook)
    assert first.change_kind is TabularChangeKind.CREATED
    assert first.metadata["needs_semantic_index"] is True

    # Indexación interrumpida: hay estructura pero no representación semántica.
    second = await persist_tabular_workbook(repo, workbook)
    assert second.change_kind is TabularChangeKind.UNCHANGED
    assert second.metadata["needs_semantic_index"] is True

    await repo.set_representations(
        context["organization"].id,
        workbook.id,
        {"structured": True, "semantic": True, "lexical": True},
    )
    third = await persist_tabular_workbook(repo, workbook)
    assert third.change_kind is TabularChangeKind.UNCHANGED
    assert third.metadata["needs_semantic_index"] is False


async def test_pipeline_version_change_forces_reprocessing(context) -> None:
    """Subir la versión del pipeline reindexa aunque el archivo no cambie."""
    from dataclasses import replace

    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    first = await persist_tabular_workbook(repo, workbook)
    assert first.change_kind is TabularChangeKind.CREATED

    fingerprint = await repo.get_fingerprint(context["organization"].id, workbook.id)
    assert fingerprint is not None
    assert fingerprint.pipeline_version == workbook.metadata["pipeline_version"]

    downgraded = replace(
        workbook,
        metadata={**workbook.metadata, "pipeline_version": "0.0-test"},
    )
    diff = await persist_tabular_workbook(repo, downgraded)
    assert diff.change_kind is TabularChangeKind.UPDATED
    assert diff.metadata["pipeline_upgraded"] is True

    fingerprint = await repo.get_fingerprint(context["organization"].id, workbook.id)
    assert fingerprint is not None
    assert fingerprint.pipeline_version == "0.0-test"


async def test_delete_for_source_and_missing_workbooks(context) -> None:
    repo = PostgresTabularRepository()
    workbook = make_workbook(context["organization"].id, context["source_id"])
    await persist_tabular_workbook(repo, workbook)

    removed = await repo.delete_missing_workbooks(
        context["organization"].id, context["source_id"], keep_external_ids=set()
    )
    assert removed == 1
    assert await repo.get_fingerprint(context["organization"].id, workbook.id) is None

    await persist_tabular_workbook(repo, workbook)
    await repo.delete_for_source(context["organization"].id, context["source_id"])
    assert await repo.get_fingerprint(context["organization"].id, workbook.id) is None

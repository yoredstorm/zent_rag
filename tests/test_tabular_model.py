# =============================================================================
# Knowledge Tabular V2 — modelo de dominio + schema inference (unit)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.tabular import (
    CellRange,
    TabularChangeKind,
    TabularColumn,
    TabularIntegrityError,
    TabularRow,
    TabularSemanticType,
    TabularSheet,
    TabularTable,
    TabularValueType,
    TabularWorkbook,
    cell_address,
    column_letter,
)
from src.knowledge.tabular.fingerprint import diff_table
from src.knowledge.tabular.schema import (
    classify_value,
    header_aliases,
    infer_semantic_type,
    normalize_name,
    profile_values,
)


def test_column_letter_and_address() -> None:
    assert column_letter(1) == "A"
    assert column_letter(26) == "Z"
    assert column_letter(27) == "AA"
    assert column_letter(52) == "AZ"
    assert cell_address(35, 2) == "B35"
    with pytest.raises(ValueError):
        column_letter(0)


def test_cell_range_invariants_and_dict_roundtrip() -> None:
    region = CellRange(min_row=4, max_row=8, min_col=1, max_col=5)
    assert region.row_count == 5
    assert region.column_count == 5
    assert region.cell_count == 25
    assert region.contains(4, 1) and not region.contains(9, 1)
    assert CellRange.from_dict(region.to_dict()) == region
    with pytest.raises(ValueError):
        CellRange(min_row=5, max_row=4, min_col=1, max_col=1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("28", TabularValueType.INTEGER),
        ("-3", TabularValueType.INTEGER),
        ("10.5", TabularValueType.FLOAT),
        ("1.234,56", TabularValueType.FLOAT),
        ("2026-01-15", TabularValueType.DATE),
        ("15/02/2026", TabularValueType.DATE),
        ("2026-01-15 08:30:00", TabularValueType.DATETIME),
        ("TRUE", TabularValueType.BOOLEAN),
        ("12,5%", TabularValueType.PERCENTAGE),
        ("$1.250,00", TabularValueType.CURRENCY),
        ("CAT10", TabularValueType.CODE),
        ("R&&&&&E&", TabularValueType.CODE),
        ("007", TabularValueType.CODE),
        ("user@example.com", TabularValueType.EMAIL),
        ("https://zent.ai/docs", TabularValueType.URL),
        ("Record 2 rules", TabularValueType.STRING),
    ],
)
def test_classify_value_keeps_codes_exact(value: str, expected: TabularValueType) -> None:
    assert classify_value(value) is expected


def test_semantic_inference_position_and_aliases() -> None:
    semantic, confidence, aliases = infer_semantic_type(
        "Start Position", value_type=TabularValueType.INTEGER
    )
    assert semantic is TabularSemanticType.POSITION
    assert confidence >= 0.8
    assert "position" in aliases
    assert "start_position" in aliases

    semantic, _, _ = infer_semantic_type("Start Pos", value_type=TabularValueType.INTEGER)
    assert semantic is TabularSemanticType.POSITION

    semantic, _, _ = infer_semantic_type("Length", value_type=TabularValueType.INTEGER)
    assert semantic is TabularSemanticType.LENGTH

    semantic, _, _ = infer_semantic_type("Description", value_type=TabularValueType.STRING)
    assert semantic is TabularSemanticType.DESCRIPTION

    semantic, _, _ = infer_semantic_type("Valid From", value_type=TabularValueType.DATE)
    assert semantic is TabularSemanticType.DATE

    # "Valid" NO debe interpretarse como identificador por el substring "id ".
    semantic, _, _ = infer_semantic_type("Validity", value_type=TabularValueType.STRING)
    assert semantic is not TabularSemanticType.IDENTIFIER


def test_normalize_and_aliases_do_not_destroy_codes() -> None:
    assert normalize_name("Código Área") == "codigo_area"
    assert normalize_name("Start Position") == "start_position"
    aliases = header_aliases("Start Position")
    assert "start_position" in aliases
    assert "position" in aliases


def test_profile_values_null_and_unique_ratio() -> None:
    profile = profile_values(["a", "", "b", "a", ""])
    assert profile.non_empty == 3
    assert profile.empty == 2
    assert profile.distinct == 2
    assert profile.null_ratio == pytest.approx(0.4)
    assert profile.unique_ratio == pytest.approx(2 / 3)
    assert profile.inferred_type is TabularValueType.STRING

    mixed = profile_values(["1", "2", "abc", "4"])
    assert mixed.inferred_type in (TabularValueType.INTEGER, TabularValueType.MIXED)
    assert mixed.mixed_values


def test_workbook_consistency_detects_broken_tree() -> None:
    from src.core.domain.tabular import TabularFormat

    workbook_id = uuid4()
    sheet_id = uuid4()
    table_id = uuid4()
    column = TabularColumn(
        id=uuid4(),
        physical_index=0,
        physical_column=1,
        excel_letter="A",
        original_name="Field Name",
        normalized_name="field_name",
        inferred_type=TabularValueType.STRING,
        semantic_type=TabularSemanticType.NAME,
    )
    row = TabularRow(physical_row=5, logical_index=0, values=("Carrier Code",))
    table = TabularTable(
        id=table_id,
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        name="Record 2 Rules",
        range=CellRange(min_row=4, max_row=5, min_col=1, max_col=1),
        columns=(column,),
        rows=(row,),
        header_rows=(4,),
    )
    sheet = TabularSheet(id=sheet_id, workbook_id=workbook_id, name="Record2", index=0, tables=(table,))
    workbook = TabularWorkbook(
        id=workbook_id,
        organization_id=uuid4(),
        external_id="obj/key.xlsx",
        filename="ATPCO_TEST.xlsx",
        format=TabularFormat.XLSX,
        content_hash="a" * 64,
        sheets=(sheet,),
    )
    workbook.check_consistency()

    broken = TabularWorkbook(
        id=workbook_id,
        organization_id=workbook.organization_id,
        external_id="obj/key.xlsx",
        filename="ATPCO_TEST.xlsx",
        format=TabularFormat.XLSX,
        content_hash="a" * 64,
        sheets=(
            TabularSheet(
                id=sheet_id,
                workbook_id=workbook_id,
                name="Record2",
                index=0,
                tables=(
                    TabularTable(
                        id=table_id,
                        workbook_id=uuid4(),  # workbook equivocado
                        sheet_id=sheet_id,
                        name="Record 2 Rules",
                        range=CellRange(min_row=1, max_row=2, min_col=1, max_col=1),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(TabularIntegrityError):
        broken.check_consistency()


def test_diff_table_detects_insert_update_delete_schema() -> None:
    workbook_id = uuid4()
    sheet_id = uuid4()
    column = TabularColumn(
        id=uuid4(),
        physical_index=0,
        physical_column=1,
        excel_letter="A",
        original_name="Field Name",
        normalized_name="field_name",
        inferred_type=TabularValueType.STRING,
    )
    rows = (
        TabularRow(physical_row=5, logical_index=0, values=("Carrier Code",), content_hash="h1"),
        TabularRow(physical_row=6, logical_index=1, values=("Tariff",), content_hash="h2"),
    )
    table = TabularTable(
        id=uuid4(),
        workbook_id=workbook_id,
        sheet_id=sheet_id,
        name="Rules",
        range=CellRange(min_row=4, max_row=6, min_col=1, max_col=1),
        columns=(column,),
        rows=rows,
        header_rows=(4,),
        schema_hash="schema-1",
    )
    unchanged = diff_table(
        table,
        {5: "h1", 6: "h2"},
        previous_schema_hash="schema-1",
    )
    assert unchanged.change_kind is TabularChangeKind.UNCHANGED
    assert not unchanged.changed

    updated = diff_table(
        table,
        {5: "h1", 6: "OLD", 7: "h9"},
        previous_schema_hash="schema-1",
    )
    assert updated.change_kind is TabularChangeKind.UPDATED
    assert updated.updated == 1
    assert updated.inserted == 0
    assert updated.deleted == 1
    assert updated.deleted_rows == (7,)

    schema = diff_table(table, {5: "h1", 6: "h2"}, previous_schema_hash="schema-old")
    assert schema.change_kind is TabularChangeKind.SCHEMA_CHANGED
    assert schema.schema_changed

    created = diff_table(table, {}, previous_schema_hash=None)
    assert created.change_kind is TabularChangeKind.CREATED
    assert created.inserted == 2
    assert created.metadata["previous_rows"] == 0


def test_discover_relations_finds_candidate_join() -> None:
    from src.core.domain.tabular import TabularFormat, TabularRelationKind
    from src.knowledge.tabular.relations import discover_relations

    workbook_id = uuid4()
    sheet_a, sheet_b = uuid4(), uuid4()

    def make_table(name: str, sheet_id, column_name: str, values: list[str], column_type):
        column = TabularColumn(
            id=uuid4(),
            physical_index=0,
            physical_column=1,
            excel_letter="A",
            original_name=column_name,
            normalized_name=normalize_name(column_name),
            inferred_type=column_type,
            unique_ratio=1.0,
        )
        rows = tuple(
            TabularRow(physical_row=index + 2, logical_index=index, values=(value,))
            for index, value in enumerate(values)
        )
        return TabularTable(
            id=uuid4(),
            workbook_id=workbook_id,
            sheet_id=sheet_id,
            name=name,
            range=CellRange(min_row=1, max_row=len(values) + 1, min_col=1, max_col=1),
            columns=(column,),
            rows=rows,
        )

    left = make_table("Rules", sheet_a, "Carrier Code", ["AA", "AM"], TabularValueType.CODE)
    right = make_table("Carriers", sheet_b, "Carrier Code", ["AA", "AM", "DL"], TabularValueType.CODE)
    workbook = TabularWorkbook(
        id=workbook_id,
        organization_id=uuid4(),
        external_id="obj/key.xlsx",
        filename="ATPCO_TEST.xlsx",
        format=TabularFormat.XLSX,
        content_hash="a" * 64,
        sheets=(
            TabularSheet(id=sheet_a, workbook_id=workbook_id, name="Rules", index=0, tables=(left,)),
            TabularSheet(id=sheet_b, workbook_id=workbook_id, name="Carriers", index=1, tables=(right,)),
        ),
    )
    relations = discover_relations(workbook)
    assert len(relations) == 1
    relation = relations[0]
    assert relation.kind is TabularRelationKind.CANDIDATE_JOIN
    assert relation.from_table_id == left.id
    assert relation.to_table_id == right.id
    assert relation.evidence["same_name"] is True
    assert relation.evidence["value_overlap"] == 1.0
    assert relation.confidence >= 0.8
    assert relation.provenance is CatalogProvenance.INFERRED

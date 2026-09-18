# =============================================================================
# Knowledge Tabular V2 — mapa del Excel + SQL-first (router y servicio)
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.tabular import PostgresTabularRepository
from src.knowledge.structure import get_parser
from src.knowledge.tabular.map import (
    TabularMapColumn,
    TabularMapTable,
    build_tabular_map,
    find_candidate_tables,
    render_tabular_map_text,
)
from src.knowledge.tabular.persistence import persist_tabular_workbook
from src.knowledge.tabular.query import (
    TabularQueryService,
    classify_tabular_question,
)
from tests import tabular_fixtures as fx


class FakeLazy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def ensure_ingested(self, organization_id, **kwargs):
        self.calls.append({"organization_id": organization_id, **kwargs})
        return None


async def _ingest(organization_id, source_id, data: bytes, filename: str):
    parser = get_parser("xlsx" if filename.endswith("xlsx") else "csv")
    document = parser.parse(
        data,
        organization_id=organization_id,
        external_id=f"obj/{filename}",
        source_id=source_id,
        source_name=filename,
    )
    repository = PostgresTabularRepository()
    await persist_tabular_workbook(repository, document.tabular)
    return repository, document


@pytest.fixture
async def context():
    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Tabular Query {uuid4().hex[:6]}"
    )
    repository, document = await _ingest(
        organization.id, uuid4(), fx.atpco_workbook_bytes(), "ATPCO_TEST.xlsx"
    )
    return {
        "organization": organization,
        "repository": repository,
        "document": document,
        "table_id": document.tabular.tables()[0].id,
    }


# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------


async def test_map_contains_tables_columns_and_aliases(context) -> None:
    tabular_map = await build_tabular_map(
        context["repository"], context["organization"].id
    )
    assert len(tabular_map.workbooks) == 1
    workbook = tabular_map.workbooks[0]
    assert workbook.filename == "ATPCO_TEST.xlsx"
    assert workbook.table_count == 1
    assert workbook.representations == {}  # aún sin indexar semánticamente

    assert len(tabular_map.tables) == 1
    table = tabular_map.tables[0]
    assert table.name == "ATPCO RECORD 2 RULES"
    assert table.sheet == "Record2"
    assert table.row_count == 4
    column = table.column_by_name("start_position")
    assert column is not None
    assert "position" in column.aliases

    rendered = render_tabular_map_text(tabular_map)
    assert "ATPCO_TEST.xlsx" in rendered
    assert "ATPCO RECORD 2 RULES" in rendered
    assert "Start Position" in rendered
    assert "position" in rendered

    # Aislamiento: otra organización no ve nada.
    other = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Tabular Query Other {uuid4().hex[:6]}"
    )
    empty = await build_tabular_map(context["repository"], other.id)
    assert empty.tables == ()


def test_candidate_tables_ranking() -> None:
    table = TabularMapTable(
        id=str(uuid4()),
        name="ATPCO RECORD 2 RULES",
        sheet="Record2",
        columns=(
            TabularMapColumn(
                normalized_name="field_name",
                original_name="Field Name",
                semantic_type="name",
                aliases=("name", "field"),
            ),
            TabularMapColumn(
                normalized_name="start_position",
                original_name="Start Position",
                semantic_type="position",
                aliases=("position", "start"),
            ),
            TabularMapColumn(
                normalized_name="length",
                original_name="Length",
                semantic_type="length",
                aliases=("length", "long"),
            ),
        ),
    )
    from src.knowledge.tabular.map import TabularMap

    tabular_map = TabularMap(organization_id=uuid4(), tables=(table,))
    candidates = find_candidate_tables(
        tabular_map, "¿qué posición tiene Carrier Code?"
    )
    assert candidates and candidates[0][0].id == table.id

    candidates = find_candidate_tables(tabular_map, "¿cuánto mide Carrier Code?")
    assert candidates and candidates[0][0].id == table.id


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _table_for_router() -> TabularMapTable:
    return TabularMapTable(
        id=str(uuid4()),
        name="ATPCO RECORD 2 RULES",
        sheet="Record2",
        columns=(
            TabularMapColumn(normalized_name="field_name", original_name="Field Name", semantic_type="name", inferred_type="string", aliases=("name", "campo")),
            TabularMapColumn(normalized_name="start_position", original_name="Start Position", semantic_type="position", inferred_type="integer", aliases=("position", "start")),
            TabularMapColumn(normalized_name="length", original_name="Length", semantic_type="length", inferred_type="integer", aliases=("length", "long")),
        ),
    )


@pytest.mark.parametrize(
    ("question", "expected_kind"),
    [
        ("¿Qué posición tiene Carrier Code?", "exact_lookup"),
        ("¿Cuánto mide Carrier Code?", "exact_lookup"),
        ("¿Cuántos campos tienen length 2?", "aggregation"),
        ("Dime todos los campos entre posición 20 y 40", "filter"),
        ("¿Qué significa el término fidelización?", "dictionary"),
    ],
)
def test_classify_tabular_question(question: str, expected_kind: str) -> None:
    intent = classify_tabular_question(question, _table_for_router())
    assert intent.kind == expected_kind


# ---------------------------------------------------------------------------
# Servicio SQL-first
# ---------------------------------------------------------------------------


async def test_exact_lookup_returns_value_and_provenance(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id,
        "What is the start position of Carrier Code?",
    )
    assert result is not None
    assert result.rows == [["Carrier Code", "28"]]
    assert result.columns == ["Field Name", "Start Position"]
    assert result.metadata["strategy"].startswith("tabular_lookup")
    provenance = result.metadata["provenance"][0]
    assert provenance["workbook"] == "ATPCO_TEST.xlsx"
    assert provenance["sheet"] == "Record2"
    assert provenance["row"] == 5
    assert provenance["cell"] == "B5"
    assert "tabular" in result.sql


async def test_spanish_length_question(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "¿Cuánto mide Carrier Code?"
    )
    assert result is not None
    assert result.rows == [["Carrier Code", "2"]]


async def test_reverse_lookup_by_value(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "¿Qué campo empieza en 30?"
    )
    assert result is not None
    assert result.rows == [["Tariff Number", "30"]]
    assert result.columns == ["Field Name", "Start Position"]


async def test_aggregation_counts_rows(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "¿Cuántos campos tienen length 2?"
    )
    assert result is not None
    assert result.rows == [["1"]]
    assert result.columns == ["count"]
    assert "COUNT(*)" in result.sql


async def test_filter_range_returns_rows(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "Dime todos los campos entre posición 20 y 40"
    )
    assert result is not None
    assert result.row_count == 4
    assert result.rows[0] == ["Carrier Code", "28"]
    assert result.rows[-1] == ["Fare Class", "36"]


async def test_semantic_question_without_exact_row_falls_back(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "¿Qué significa el concepto ZZZ desconocido?"
    )
    assert result is None


async def test_customer_role_cannot_aggregate(context) -> None:
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id,
        "¿Cuántos campos tienen length 2?",
        role="customer",
    )
    assert result is None


async def test_multi_label_columns_and_underscore_values() -> None:
    """Excel real: dos columnas "nombre" (Standard Name / Field Name) y valores 1_100."""
    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Tabular MultiLabel {uuid4().hex[:6]}"
    )
    repository, _document = await _ingest(
        organization.id,
        uuid4(),
        fx.duplicate_headers_workbook_bytes(),
        "ATPCO_Attributes.xlsx",
    )
    service = TabularQueryService(repository)

    # Label en Field Name (no en la primera columna NAME) + columna Location.
    result = await service.try_answer(
        organization.id, "¿Cuál es la location de Record Type?"
    )
    assert result is not None
    assert result.rows == [["Record Type", "1"]]
    assert result.columns == ["Field Name", "Location"]

    # Token con guion bajo: 1_100 debe matchear el valor exacto, no "1".
    result = await service.try_answer(
        organization.id, "¿Qué campo tiene location 1_100?"
    )
    assert result is not None
    assert result.rows[0][-1] == "1_100"
    assert result.rows[0][0] == "Date Table 157"


async def test_ambiguous_tables_fall_back_to_rag(context) -> None:
    # Segunda tabla con la misma fila Carrier Code y otro valor.
    alt_csv = (
        "Field Name,Start Position,End Position,Length\n"
        "Carrier Code,99,100,2\n"
        "Tariff Number,101,103,3\n"
    ).encode("utf-8")
    _repo, _document = await _ingest(
        context["organization"].id, uuid4(), alt_csv, "alt_rules.csv"
    )
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "What is the start position of Carrier Code?"
    )
    assert result is None  # ambigüedad: dos tablas con respuestas distintas


async def test_lazy_hook_called_when_no_tables() -> None:
    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Tabular Query Empty {uuid4().hex[:6]}"
    )
    repository = PostgresTabularRepository()
    lazy = FakeLazy()
    service = TabularQueryService(repository, lazy_ingestion=lazy)
    result = await service.try_answer(
        organization.id, "What is the start position of Carrier Code?"
    )
    assert result is None
    assert lazy.calls, "la auto-ingesta debe dispararse cuando no hay tablas"
    assert lazy.calls[0]["organization_id"] == organization.id


# ---------------------------------------------------------------------------
# P0: scoring por label más largo, matches múltiples y modo lista
# ---------------------------------------------------------------------------


def test_resolve_exact_lookup_prefers_longest_label() -> None:
    """`Carrier Code` (fila 5775) le gana a `Carrier` (fila 5), no la primera fila."""
    from src.knowledge.tabular.lookup import resolve_exact_lookup

    columns = [
        {
            "normalized_name": "field_name",
            "original_name": "Field Name",
            "semantic_type": "name",
            "physical_column": 1,
            "aliases": [],
        },
        {
            "normalized_name": "start_position",
            "original_name": "Start Position",
            "semantic_type": "position",
            "physical_column": 2,
            "aliases": ["position"],
        },
    ]
    rows = [
        {"physical_row": 5, "values": {"field_name": "Carrier", "start_position": "14"}},
        {"physical_row": 5775, "values": {"field_name": "Carrier Code", "start_position": "6"}},
        {"physical_row": 5790, "values": {"field_name": "Carrier Code", "start_position": "11"}},
    ]
    result = resolve_exact_lookup(
        "What is the position of Carrier Code?",
        table={"name": "T", "sheet": "S"},
        columns=columns,
        rows=rows,
    )
    assert result.value == "6"
    assert result.physical_row == 5775
    assert result.cell_address == "B5775"
    assert result.row_matches == 2


async def test_list_intent_returns_rows_and_total(context) -> None:
    """"Which fields have length 2?" → filas con Length=2 + total."""
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "Which fields have length 2?"
    )
    assert result is not None
    metadata = result.metadata or {}
    assert metadata.get("strategy") == "tabular_lookup:value+label:list"
    assert metadata.get("total", 0) >= 1
    assert result.columns[0] == "Field Name"
    labels = [row[0] for row in result.rows]
    assert all(labels)
    assert metadata.get("provenance")


async def test_dictionary_question_returns_description_and_provenance(context) -> None:
    """P4: "¿qué significa X?" responde la doc de la fila, determinista."""
    service = TabularQueryService(context["repository"])
    result = await service.try_answer(
        context["organization"].id, "¿Qué significa Carrier Code?"
    )
    assert result is not None
    metadata = result.metadata or {}
    assert metadata.get("strategy") == "tabular_dictionary"
    assert result.columns == ["Field Name", "column", "definition"]
    assert result.rows[0][0] == "Carrier Code"
    assert result.rows[0][1] == "Description"
    assert "Identifies carrier" in result.rows[0][2]
    provenance = (metadata.get("provenance") or [{}])[0]
    assert provenance.get("row") == 5
    assert provenance.get("cell") == "E5"

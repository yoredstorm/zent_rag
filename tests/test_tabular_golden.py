# =============================================================================
# Knowledge Tabular V2 — golden dataset tabular (§34)
# =============================================================================
# Flujo completo: xlsx → parser → representación estructurada (Postgres) +
# representación semántica (chunks). Para cada caso del golden:
#   - respuesta exacta vía structured lookup (SIN embeddings);
#   - recall de tabla/fila/columnas vía ranking lexical sobre los chunks
#     (metadata de tabla/fila/columnas indexada);
#   - citation accuracy (tabla + fila + columna).
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.tabular import PostgresTabularRepository
from src.knowledge.structure import get_parser
from src.knowledge.tabular.chunker import TabularChunkingConfig, chunk_tabular_workbook
from src.knowledge.tabular.lookup import resolve_exact_lookup
from src.knowledge.tabular.persistence import persist_tabular_workbook
from src.rag.evaluation.tabular_metrics import (
    column_recall_at_k,
    evaluate_tabular_case,
    exact_value_accuracy,
    load_tabular_golden,
    row_recall_at_k,
    table_recall_at_k,
)
from tests import tabular_fixtures as fx

GOLDEN_PATH = Path(__file__).parent / "golden" / "tabular_golden.json"


def _rank_chunks(question: str, chunks, k: int):
    from src.infrastructure.qdrant.bm25 import encode_sparse

    query_tokens = encode_sparse(question)
    scored = []
    for chunk in chunks:
        chunk_tokens = encode_sparse(chunk.content)
        overlap = sum(
            min(count, chunk_tokens.get(token, 0.0))
            for token, count in query_tokens.items()
        )
        if overlap > 0:
            scored.append((overlap, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _score, chunk in scored[:k]]


def _retrieval_view(chunks) -> tuple[list[str], list[int], list[str]]:
    tables: list[str] = []
    rows: list[int] = []
    columns: list[str] = []
    for chunk in chunks:
        metadata = chunk.metadata
        table = metadata.get("table_name")
        if table and table not in tables:
            tables.append(table)
        physical_row = metadata.get("physical_row")
        if physical_row is not None and int(physical_row) not in rows:
            rows.append(int(physical_row))
        normalized_to_original = dict(
            zip(metadata.get("columns") or [], metadata.get("column_names") or [])
        )
        present = metadata.get("values")
        if isinstance(present, dict) and present:
            for normalized in present:
                original = normalized_to_original.get(normalized)
                if original and original not in columns:
                    columns.append(original)
        else:
            for original in metadata.get("column_names") or []:
                if original and original not in columns:
                    columns.append(original)
    return tables, rows, columns


@pytest.fixture
async def golden_context():
    organization = await PostgresOrganizationRepository().create_organization(
        uuid4(), f"Golden Tabular {uuid4().hex[:6]}"
    )
    parser = get_parser("xlsx")
    document = parser.parse(
        fx.atpco_workbook_bytes(),
        organization_id=organization.id,
        external_id="obj/ATPCO_TEST.xlsx",
        source_id=uuid4(),
        source_name="ATPCO_TEST.xlsx",
    )
    document.check_consistency()
    repo = PostgresTabularRepository()
    await persist_tabular_workbook(repo, document.tabular)
    return {"organization": organization, "document": document, "repo": repo}


async def test_tabular_golden_dataset(golden_context, capsys) -> None:
    context = golden_context
    document = context["document"]
    repo: PostgresTabularRepository = context["repo"]
    organization_id = context["organization"].id

    tables = await repo.list_tables(organization_id)
    assert len(tables) == 1
    table_meta = tables[0]
    table_id = UUID(table_meta["id"])
    schema = await repo.get_table(organization_id, table_id)
    assert schema is not None
    rows = await repo.fetch_rows(organization_id, table_id, limit=100)

    chunks = chunk_tabular_workbook(
        document, config=TabularChunkingConfig(row_group_size=10)
    )
    cases = load_tabular_golden(GOLDEN_PATH)
    assert len(cases) >= 4

    from src.knowledge.tabular.query import TabularQueryService

    sql_service = TabularQueryService(repo)

    exact_hits = 0
    citation_hits = 0
    sql_first_hits = 0
    table_recall = 0.0
    row_recall = 0.0
    column_recall = 0.0

    for case in cases:
        lookup = resolve_exact_lookup(
            case.question, table=table_meta, columns=schema["columns"], rows=rows
        )
        answer = lookup.value
        exact = exact_value_accuracy(answer, case.expected_answer)
        exact_hits += int(exact)

        # SQL-first (camino productivo): mismo golden por la representación
        # estructurada, sin embeddings ni LLM.
        sql_result = await sql_service.try_answer(organization_id, case.question)
        assert sql_result is not None, f"SQL-first no resolvió {case.id}"
        strategy = str((sql_result.metadata or {}).get("strategy", ""))
        # value+label (incluye modo lista) responde el label en la 1ª columna.
        if "value+label" in strategy:
            sql_answer = sql_result.rows[0][0] if sql_result.rows else None
        else:
            sql_answer = sql_result.rows[0][-1] if sql_result.rows else None
        sql_first_hits += int(exact_value_accuracy(sql_answer, case.expected_answer))
        provenance = (sql_result.metadata or {}).get("provenance") or [{}]
        assert provenance[0].get("table") == case.expected_table
        if case.expected_row is not None:
            assert provenance[0].get("row") == case.expected_row

        retrieved = _rank_chunks(case.question, chunks, k=5)
        retrieved_tables, retrieved_rows, retrieved_columns = _retrieval_view(retrieved)

        citation = {
            "table": lookup.table,
            "row": lookup.physical_row,
            "column": lookup.column,
        }
        result = evaluate_tabular_case(
            case,
            answer=answer,
            retrieved_tables=retrieved_tables,
            retrieved_rows=retrieved_rows,
            retrieved_columns=retrieved_columns,
            citation=citation,
            k=5,
        )
        table_recall += result.table_hit
        row_recall += result.row_hit
        column_recall += result.columns_hit
        citation_hits += int(result.citation_ok)
        with capsys.disabled():
            print(  # noqa: T201 (resumen de evaluación)
                f"[golden] {case.id}: answer={answer!r} "
                f"table={result.table_hit} row={result.row_hit} "
                f"cols={result.columns_hit:.2f} exact={result.exact_value} "
                f"citation={result.citation_ok}"
            )

    total = len(cases)
    metrics = {
        "table_recall@5": table_recall / total,
        "row_recall@5": row_recall / total,
        "column_recall@5": column_recall / total,
        "exact_value_accuracy": exact_hits / total,
        "sql_first_accuracy": sql_first_hits / total,
        "citation_accuracy": citation_hits / total,
    }
    with capsys.disabled():
        print(f"[golden] metrics: {metrics}")  # noqa: T201 (resumen de evaluación)

    # Response quality gates: la representación estructurada responde exacto y
    # la metadata indexada permite llegar a tabla/fila/columna correctas.
    assert metrics["table_recall@5"] == 1.0
    assert metrics["row_recall@5"] >= 0.75
    assert metrics["column_recall@5"] >= 0.75
    assert metrics["exact_value_accuracy"] == 1.0
    assert metrics["sql_first_accuracy"] == 1.0
    assert metrics["citation_accuracy"] == 1.0


async def test_golden_metrics_helpers_are_exact() -> None:
    cases = load_tabular_golden(GOLDEN_PATH)
    carrier = cases[0]
    assert table_recall_at_k(["Other", "ATPCO RECORD 2 RULES"], carrier.expected_table, 2) == 1.0
    assert table_recall_at_k(["Other"], carrier.expected_table, 1) == 0.0
    assert row_recall_at_k([5, 6], carrier.expected_row, 2) == 1.0
    assert row_recall_at_k([6], carrier.expected_row, 1) == 0.0
    assert column_recall_at_k(["Field Name", "Start Position"], carrier.expected_columns, 2) == 1.0
    assert column_recall_at_k(["Field Name"], carrier.expected_columns, 2) == 0.5
    assert exact_value_accuracy("28", "28") == 1.0
    assert exact_value_accuracy(" 28 ", "28") == 1.0
    assert exact_value_accuracy("29", "28") == 0.0
    assert exact_value_accuracy(None, "28") == 0.0

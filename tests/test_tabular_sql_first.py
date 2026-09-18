# =============================================================================
# Knowledge Tabular V2 — SQL-first en el orquestador (prioridad SQL)
# =============================================================================
# Un solo camino de decisión: tabular estructurado ANTES que SQL Expert LLM y
# vector search; si no hay señal, cae al flujo normal sin romper nada.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.ports.sql_expert import SqlQueryResult
from tests.test_lazy_ingestion import (  # reutiliza fakes existentes
    FakeCache,
    FakeEmbed,
    FakeLLM,
    FakeSqlExpert,
    FakeVectorStore,
    _build_orchestrator,
    _chunk_ctx,
    _organization,
)


class FakeTabularQuery:
    def __init__(self, result: SqlQueryResult | None) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def try_answer(self, organization_id, question, **kwargs):
        self.calls.append(
            {"organization_id": organization_id, "question": question, **kwargs}
        )
        return self.result


def _tabular_result() -> SqlQueryResult:
    return SqlQueryResult(
        sql="-- zent tabular:Record2.ATPCO RECORD 2 RULES\n"
        "SELECT values->>'field_name', values->>'start_position' FROM tabular_rows;",
        columns=["Field Name", "Start Position"],
        rows=[["Carrier Code", "28"]],
        row_count=1,
        metadata={
            "strategy": "tabular_lookup:row_label+column",
            "confidence": 0.95,
            "tables": ["ATPCO RECORD 2 RULES"],
            "provenance": [
                {
                    "workbook": "ATPCO_TEST.xlsx",
                    "sheet": "Record2",
                    "table": "ATPCO RECORD 2 RULES",
                    "row": 5,
                    "cell": "B5",
                    "column": "Start Position",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_tabular_sql_first_wins_over_sql_expert() -> None:
    organization = _organization()
    vectors = FakeVectorStore()
    vectors.enqueue_search(_chunk_ctx())
    llm = FakeLLM(content="Carrier Code empieza en la posición 28.")
    expert = FakeSqlExpert()  # no debe llamarse
    tabular = FakeTabularQuery(_tabular_result())
    orchestrator = _build_orchestrator(
        organization=organization,
        vector_store=vectors,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        sql_expert=expert,
    )
    orchestrator._tabular_query = tabular
    orchestrator._tabular_sql_first = True

    result = await orchestrator.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="¿Qué posición tiene Carrier Code?",
        use_cache=False,
    )

    assert tabular.calls, "el servicio tabular no fue consultado"
    assert result.method == "sql"
    assert result.sql_query and "tabular" in result.sql_query
    assert result.structured_output["rows"] == [["Carrier Code", "28"]]
    assert result.structured_output["columns"] == ["Field Name", "Start Position"]
    assert expert.calls == 0, "el SQL Expert LLM no debe correr si tabular respondió"


@pytest.mark.asyncio
async def test_tabular_sql_first_falls_back_when_no_signal() -> None:
    organization = _organization()
    vectors = FakeVectorStore()
    vectors.enqueue_search(_chunk_ctx())
    vectors.enqueue_search(_chunk_ctx())
    llm = FakeLLM(content="Respuesta normal por RAG.")
    expert = FakeSqlExpert()
    tabular = FakeTabularQuery(None)
    orchestrator = _build_orchestrator(
        organization=organization,
        vector_store=vectors,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
        sql_expert=expert,
    )
    orchestrator._tabular_query = tabular
    orchestrator._tabular_sql_first = True

    result = await orchestrator.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="¿Qué significa el concepto de fidelización?",
        use_cache=False,
    )

    assert tabular.calls
    assert result.method == "rag"
    assert expert.calls == 1, "sin señal tabular, el flujo SQL existente sigue"


@pytest.mark.asyncio
async def test_tabular_sql_first_disabled_skips_service() -> None:
    organization = _organization()
    vectors = FakeVectorStore()
    vectors.enqueue_search(_chunk_ctx())
    llm = FakeLLM(content="Respuesta por RAG.")
    tabular = FakeTabularQuery(_tabular_result())
    orchestrator = _build_orchestrator(
        organization=organization,
        vector_store=vectors,
        llm=llm,
        embed=FakeEmbed(),
        cache=FakeCache(),
    )
    orchestrator._tabular_query = tabular
    orchestrator._tabular_sql_first = False

    result = await orchestrator.execute(
        organization_id=organization.id,
        user_id=uuid4(),
        query="¿Qué posición tiene Carrier Code?",
        use_cache=False,
    )

    assert tabular.calls == []
    assert result.method == "rag"

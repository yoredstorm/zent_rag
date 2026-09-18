# =============================================================================
# query_tabular_data — tool de agentes para consultas exactas sobre Excel/CSV
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.agents.tools.base import ToolContext
from src.agents.tools.tools_builtin import QueryTabularDataTool
from src.core.ports.sql_expert import SqlQueryResult


class FakeTabularService:
    def __init__(self, result: SqlQueryResult | None) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def try_answer(self, organization_id, query, **kwargs):
        self.calls.append(
            {"organization_id": organization_id, "query": query, **kwargs}
        )
        return self.result


def _result() -> SqlQueryResult:
    return SqlQueryResult(
        sql="-- zent tabular\nSELECT ...",
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


def _context() -> ToolContext:
    return ToolContext(
        tenant_id=uuid4(),
        role="admin",
        org_config={"source_ids": [str(uuid4())]},
    )


@pytest.mark.asyncio
async def test_query_tabular_data_returns_value_and_provenance() -> None:
    service = FakeTabularService(_result())
    tool = QueryTabularDataTool(service)

    result = await tool.execute(_context(), {"query": "posición de Carrier Code"})

    assert result.error is None
    assert "Start Position: 28" in result.output
    assert "ATPCO_TEST.xlsx" in result.output
    assert "Row" in result.output or "row: 5" in result.output
    assert "B5" in result.output
    assert result.meta["matched"] is True
    assert result.meta["strategy"] == "tabular_lookup:row_label+column"
    assert service.calls and service.calls[0]["source_ids"]


@pytest.mark.asyncio
async def test_query_tabular_data_falls_back_without_match() -> None:
    service = FakeTabularService(None)
    tool = QueryTabularDataTool(service)

    result = await tool.execute(_context(), {"query": "algo sin match exacto"})

    assert result.error is None
    assert "search_knowledge" in result.output
    assert result.meta["matched"] is False


@pytest.mark.asyncio
async def test_query_tabular_data_requires_query() -> None:
    tool = QueryTabularDataTool(FakeTabularService(None))
    result = await tool.execute(_context(), {})
    assert result.error == "query is required"

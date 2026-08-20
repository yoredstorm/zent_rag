# =============================================================================
# Tests — SQL Expert: ORDER BY estable + filtro completed en ventas
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

import pytest

from src.agents.tools.sql_expert_postgres import (
    PostgresSqlExpert,
    load_sql_heuristics,
    stabilize_sql,
)
from src.core.domain.entities import LLMResponse
from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports.sql_expert import SqlQueryResult, SqlValidationError

# El filtro "ventas completed" es una heurística del VERTICAL demo_farmacia
# (el core es agnóstico). Registrarla explícitamente en los tests.
load_sql_heuristics(["src.verticals.demo_farmacia.heuristics"])

_LAST_SALE_SQL = """
SELECT p.name AS producto, p.price, s.quantity, s.payment_method, s.sale_date
FROM farmacia.sales s
JOIN farmacia.products p ON s.product_id = p.id
ORDER BY s.sale_date DESC
LIMIT 1
"""


def _flat(sql: str) -> str:
    return " ".join(sql.lower().split())


def test_stabilize_appends_id_desc_when_order_by_date_and_limit() -> None:
    out = stabilize_sql(_LAST_SALE_SQL, "cuál es el último producto vendido")
    flat = _flat(out)
    assert "limit 1" in flat
    assert re.search(r"order by .+\.id desc", flat)
    assert "sale_date" in flat


def test_stabilize_is_idempotent_when_id_already_in_order_by() -> None:
    sql = """
    SELECT p.name FROM farmacia.sales s
    JOIN farmacia.products p ON s.product_id = p.id
    ORDER BY s.sale_date DESC, s.id DESC
    LIMIT 1
    """
    out = stabilize_sql(sql, "último producto vendido")
    assert _flat(out).count(".id desc") == 1


def test_stabilize_skips_when_no_limit() -> None:
    sql = "SELECT p.name FROM farmacia.sales s ORDER BY s.sale_date DESC"
    out = stabilize_sql(sql, "ventas recientes")
    assert ".id" not in _flat(out) or "id desc" not in _flat(out)


def test_stabilize_adds_completed_filter_for_last_sold_question() -> None:
    out = stabilize_sql(_LAST_SALE_SQL, "cuál es el último producto vendido")
    flat = _flat(out)
    assert "order_status" in flat
    assert "completed" in flat


def test_stabilize_does_not_duplicate_completed_filter() -> None:
    sql = """
    SELECT p.name FROM farmacia.sales s
    JOIN farmacia.products p ON s.product_id = p.id
    WHERE s.order_status = 'completed'
    ORDER BY s.sale_date DESC
    LIMIT 1
    """
    out = stabilize_sql(sql, "último producto vendido")
    assert _flat(out).count("order_status") == 1


def test_stabilize_skips_completed_filter_when_not_a_sale_question() -> None:
    sql = """
    SELECT name, price FROM farmacia.products
    ORDER BY name
    LIMIT 10
    """
    out = stabilize_sql(sql, "lista de productos")
    assert "order_status" not in _flat(out)


def test_stabilize_is_deterministic_across_calls() -> None:
    a = stabilize_sql(_LAST_SALE_SQL, "cuál es el último producto vendido")
    b = stabilize_sql(_LAST_SALE_SQL, "cuál es el último producto vendido")
    assert a == b
    assert "id desc" in _flat(a)
    assert "completed" in _flat(a)


def test_stabilize_returns_original_on_unparseable_sql() -> None:
    raw = "NOT VALID SQL )))"
    assert stabilize_sql(raw, "último vendido") == raw


def test_stabilize_does_not_append_id_on_group_by_queries() -> None:
    """Un agregado con GROUP BY no puede ordenar por s.id (rompe el GROUP BY)."""
    sql = """
    SELECT p.name, SUM(s.quantity) AS total_vendido
    FROM farmacia.sales s
    JOIN farmacia.products p ON s.product_id = p.id
    GROUP BY p.id, p.name
    ORDER BY total_vendido DESC
    LIMIT 1
    """
    out = stabilize_sql(sql, "cuál es el producto más vendido")
    assert "s.id" not in _flat(out)
    assert "group by" in _flat(out)


# ---------------------------------------------------------------------------
# Auto-reparación de SQL inválido
# ---------------------------------------------------------------------------

_BROKEN_SQL = (
    "SELECT p.name, SUM(s.quantity) AS total FROM farmacia.sales s "
    "JOIN farmacia.products p ON s.product_id = p.id "
    "GROUP BY p.id, p.name ORDER BY total DESC, s.id DESC LIMIT 1"
)

_REPAIRED_SQL = (
    "SELECT p.name, SUM(s.quantity) AS total FROM farmacia.sales s "
    "JOIN farmacia.products p ON s.product_id = p.id "
    "GROUP BY p.id, p.name ORDER BY total DESC LIMIT 1"
)


class _ScriptedLLM:
    """LLM que devuelve respuestas predefinidas en orden."""

    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls: list[dict] = []

    async def generate(self, **kwargs) -> LLMResponse:
        idx = min(self.calls.__len__(), len(self.contents) - 1)
        self.calls.append(kwargs)
        return LLMResponse(content=self.contents[idx], model="fake-llm")


class _RepairExpert(PostgresSqlExpert):
    def __init__(self, llm) -> None:
        super().__init__(llm)
        self.validated: list[str] = []

    async def _discover_sources(self, organization_id: UUID) -> list[DataSource]:
        return [
            DataSource(
                schema_name="farmacia",
                table_name="sales",
                columns=[
                    ColumnMeta(name="id", data_type="uuid", is_nullable=False),
                    ColumnMeta(name="product_id", data_type="uuid", is_nullable=False),
                    ColumnMeta(name="quantity", data_type="integer", is_nullable=False),
                ],
                row_count=1,
            )
        ]

    async def validate_sql(
        self, sql: str, sources: list[DataSource], role: str, organization_id: UUID
    ) -> str:
        self.validated.append(sql)
        if len(self.validated) == 1:
            raise SqlValidationError('column "s.id" must appear in GROUP BY', sql)
        return sql

    async def _run_query(self, sql: str) -> SqlQueryResult:
        return SqlQueryResult(
            sql=sql,
            columns=["producto", "total"],
            rows=[["Paracetamol", "42"]],
            row_count=1,
        )


@pytest.mark.asyncio
async def test_repairs_sql_after_validation_failure() -> None:
    llm = _ScriptedLLM([_BROKEN_SQL, _REPAIRED_SQL])
    expert = _RepairExpert(llm)
    result = await expert.execute(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        question="cuál es el producto más vendido",
        role="admin",
    )
    assert result.error is None
    assert result.row_count == 1
    assert len(expert.validated) == 2
    assert "GROUP BY" in result.sql and "ORDER BY" in result.sql
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_repair_gives_up_when_llm_cannot_fix() -> None:
    llm = _ScriptedLLM([_BROKEN_SQL, "NO_QUERY"])
    expert = _RepairExpert(llm)
    result = await expert.execute(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        question="cuál es el producto más vendido",
        role="admin",
    )
    assert result.error is not None
    assert len(expert.validated) == 1

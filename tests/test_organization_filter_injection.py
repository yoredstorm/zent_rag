# =============================================================================
# Tests — Organization filter injection (SQL Expert, multi-organization isolation)
# =============================================================================
# Regresión: el filtro organization_id debe inyectarse como WHERE válido en
# queries con JOINs (sqlglot >= 30 usa args["from_"] y nodos exp.Where).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.agents.tools.sql_expert_postgres import PostgresSqlExpert
from src.core.domain.services import ColumnMeta, DataSource

_OID = UUID("00000000-0000-0000-0000-000000000001")


def _col(name: str, data_type: str = "uuid") -> ColumnMeta:
    return ColumnMeta(name=name, data_type=data_type, is_nullable=False)


_SOURCES = [
    DataSource(
        "farmacia",
        "sales",
        columns=[_col("id"), _col("product_id"), _col("customer_id"), _col("organization_id")],
        row_count=1,
    ),
    DataSource(
        "farmacia",
        "products",
        columns=[_col("id"), _col("name"), _col("organization_id")],
        row_count=1,
    ),
    DataSource(
        "farmacia",
        "customers",
        columns=[_col("id"), _col("name"), _col("organization_id")],
        row_count=1,
    ),
]


def _expert() -> PostgresSqlExpert:
    return PostgresSqlExpert.__new__(PostgresSqlExpert)


def test_organization_filter_injected_on_all_join_tables() -> None:
    sql = (
        "SELECT p.name, s.quantity FROM farmacia.sales AS s "
        "JOIN farmacia.products AS p ON s.product_id = p.id "
        "JOIN farmacia.customers AS c ON s.customer_id = c.id "
        "ORDER BY s.sale_date DESC, s.id DESC LIMIT 1"
    )
    out = _expert()._inject_organization_filter(sql, _OID, _SOURCES)
    assert "WHERE" in out, out
    assert "s.organization_id = CAST" in out, out
    assert "p.organization_id = CAST" in out, out
    assert "c.organization_id = CAST" in out, out
    # El SQL resultante debe parsear y conservar ORDER BY / LIMIT
    assert "ORDER BY s.sale_date DESC, s.id DESC LIMIT 1" in out


def test_organization_filter_combines_with_existing_where() -> None:
    sql = (
        "SELECT p.name FROM farmacia.sales AS s "
        "JOIN farmacia.products AS p ON s.product_id = p.id "
        "WHERE s.order_status = 'completed' ORDER BY s.sale_date DESC LIMIT 1"
    )
    out = _expert()._inject_organization_filter(sql, _OID, _SOURCES)
    assert "s.order_status = 'completed'" in out, out
    assert "s.organization_id = CAST" in out, out
    assert "p.organization_id = CAST" in out, out


def test_organization_filter_overwrites_llm_written_organization_predicate() -> None:
    sql = (
        "SELECT p.name FROM farmacia.sales AS s "
        "JOIN farmacia.products AS p ON s.product_id = p.id "
        "WHERE organization_id = '11111111-1111-1111-1111-111111111111'::uuid "
        "ORDER BY s.sale_date DESC LIMIT 1"
    )
    out = _expert()._inject_organization_filter(sql, _OID, _SOURCES)
    assert str(_OID) in out
    assert "11111111-1111-1111-1111-111111111111" not in out


def test_organization_filter_skips_tables_without_organization_column() -> None:
    sources = [
        DataSource(
            "farmacia",
            "sales",
            columns=[_col("id"), _col("organization_id")],
            row_count=1,
        ),
        DataSource(
            "farmacia",
            "labels",
            columns=[_col("id"), _col("name")],  # sin organization_id
            row_count=1,
        ),
    ]
    sql = (
        "SELECT s.id, l.name FROM farmacia.sales AS s "
        "JOIN farmacia.labels AS l ON s.id = l.id LIMIT 10"
    )
    out = _expert()._inject_organization_filter(sql, _OID, sources)
    assert "s.organization_id = CAST" in out, out
    assert "l.organization_id" not in out, out

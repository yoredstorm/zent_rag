# =============================================================================
# Tests — SQL Expert: ORDER BY estable + filtro completed en ventas
# =============================================================================
from __future__ import annotations

import re

from src.infrastructure.sql_expert import stabilize_sql

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

# =============================================================================
# P20-05 - tools comerciales read-only y contratos de salida.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from src.agents.tools.base import ToolContext
from src.agents.tools.catalog_tools import (
    FindProductsTool,
    GetPriceAndStockTool,
    GetProductTool,
    _search_terms,
)

ORG = UUID("00000000-0000-0000-0000-000000000001")
WS = UUID("00000000-0000-0000-0000-000000000002")
AGENT = UUID("00000000-0000-0000-0000-000000000003")


def _ctx() -> ToolContext:
    return ToolContext(
        tenant_id=ORG,
        user_id=None,
        agent_id=AGENT,
        role="admin",
        permissions=frozenset({"*"}),
        org_config={"source_ids": ["source-1"]},
    )


class _FakeSession:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.closed = False

    async def execute(self, statement, _params=None):
        if "SET TRANSACTION" in str(statement).upper():
            return SimpleNamespace(fetchall=lambda: [])
        return SimpleNamespace(
            fetchall=lambda: [SimpleNamespace(_mapping=row) for row in self.rows]
        )

    async def close(self) -> None:
        self.closed = True


def _source() -> dict:
    return {
        "source_id": "source-1",
        "connector_id": "00000000-0000-0000-0000-000000000004",
        "workspace_id": str(WS),
        "source_mode": "schema_only",
        "resource_ref": "bodega.product_catalog_v",
    }


def test_search_terms_keep_numeric_presentation() -> None:
    assert _search_terms("arroz de 1 kg") == ["arroz", "1", "kg"]


@pytest.mark.asyncio
async def test_find_products_returns_backend_price_and_stock(monkeypatch) -> None:
    session = _FakeSession(
        [
            {
                "sku": "BD-ARROZ-01",
                "name": "Arroz extra 1 kg",
                "category": "abarrotes",
                "unit": "kg",
                "price": "4.80",
                "currency": "PEN",
                "available": 53,
            }
        ]
    )

    async def _fake_source(*_args, **_kwargs):
        return _source(), session, None

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _fake_source,
    )
    result = await FindProductsTool().execute(_ctx(), {"query": "arroz"})

    payload = json.loads(result.output)
    assert payload["status"] == "FOUND"
    assert payload["data"][0]["sku"] == "BD-ARROZ-01"
    assert payload["data"][0]["price"] == "4.80"
    assert payload["data"][0]["currency"] == "PEN"
    assert payload["data"][0]["available"] == 53
    assert session.closed is True


@pytest.mark.asyncio
async def test_find_products_without_query_lists_catalog(monkeypatch) -> None:
    session = _FakeSession(
        [
            {
                "sku": "BD-ARROZ-01",
                "name": "Arroz extra 1 kg",
                "category": "abarrotes",
                "unit": "kg",
                "price": "4.80",
                "currency": "PEN",
                "available": 53,
            }
        ]
    )

    async def _fake_source(*_args, **_kwargs):
        return _source(), session, None

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _fake_source,
    )
    result = await FindProductsTool().execute(_ctx(), {})

    payload = json.loads(result.output)
    assert result.error is None
    assert payload["status"] == "FOUND"
    assert payload["data"][0]["sku"] == "BD-ARROZ-01"


@pytest.mark.asyncio
async def test_get_price_and_stock_computes_decimal_line_total(monkeypatch) -> None:
    session = _FakeSession(
        [
            {
                "sku": "BD-ARROZ-01",
                "name": "Arroz extra 1 kg",
                "category": "abarrotes",
                "unit": "kg",
                "price": "4.80",
                "currency": "PEN",
                "available": 53,
            }
        ]
    )

    async def _fake_source(*_args, **_kwargs):
        return _source(), session, None

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _fake_source,
    )
    result = await GetPriceAndStockTool().execute(
        _ctx(), {"sku": "BD-ARROZ-01", "quantity": 2}
    )

    payload = json.loads(result.output)
    assert payload["status"] == "FOUND"
    assert payload["data"]["price"] == "4.80"
    assert payload["data"]["line_total"] == "9.60"
    assert payload["data"]["observed_at"]


@pytest.mark.asyncio
async def test_get_price_and_stock_rejects_insufficient_stock(monkeypatch) -> None:
    session = _FakeSession(
        [
            {
                "sku": "BD-ARROZ-01",
                "name": "Arroz extra 1 kg",
                "category": "abarrotes",
                "unit": "kg",
                "price": "4.80",
                "currency": "PEN",
                "available": 1,
            }
        ]
    )

    async def _fake_source(*_args, **_kwargs):
        return _source(), session, None

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _fake_source,
    )
    result = await GetPriceAndStockTool().execute(
        _ctx(), {"sku": "BD-ARROZ-01", "quantity": 2}
    )

    payload = json.loads(result.output)
    assert payload["status"] == "INSUFFICIENT_STOCK"
    assert payload["data"]["available"] == 1


@pytest.mark.asyncio
async def test_get_product_not_found_is_not_500(monkeypatch) -> None:
    session = _FakeSession([])

    async def _fake_source(*_args, **_kwargs):
        return _source(), session, None

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _fake_source,
    )
    result = await GetProductTool().execute(_ctx(), {"sku": "NO-EXISTE"})

    payload = json.loads(result.output)
    assert payload["status"] == "NOT_FOUND"
    assert payload["data"] is None
    assert result.error is None


@pytest.mark.asyncio
async def test_catalog_tool_propagates_permission_denied(monkeypatch) -> None:
    async def _denied(*_args, **_kwargs):
        return None, None, "PERMISSION_DENIED: sin grant"

    monkeypatch.setattr(
        "src.agents.tools.catalog_tools._authorized_catalog_source",
        _denied,
    )
    result = await GetPriceAndStockTool().execute(
        _ctx(), {"sku": "BD-ARROZ-01", "quantity": 1}
    )

    assert result.error is not None
    assert result.error.startswith("PERMISSION_DENIED")

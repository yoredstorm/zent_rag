# =============================================================================
# P20 - consulta conversacional contra una BD externa (no Managed DB interna)
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.agents.tools.base import ToolContext
from src.agents.tools.sql_expert_postgres import (
    PostgresSqlExpert,
    _preferred_catalog_source,
)
from src.agents.tools.tools_builtin import QueryDatabaseTool
from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports.sql_expert import SqlQueryResult

ORG = UUID("00000000-0000-0000-0000-000000000001")
WS = UUID("00000000-0000-0000-0000-000000000002")
CONNECTOR = UUID("00000000-0000-0000-0000-000000000003")
SOURCE = "00000000-0000-0000-0000-000000000004"


class _FakeLLM:
    async def generate(self, **_kwargs):  # pragma: no cover - no se usa
        raise AssertionError("LLM no debe invocarse en esta prueba")


def _context(source_ids: list[str] | None = None) -> ToolContext:
    return ToolContext(
        tenant_id=ORG,
        user_id=None,
        role="admin",
        permissions=frozenset({"*"}),
        org_config={"source_ids": source_ids or [SOURCE]},
        agent_config={"source_ids": source_ids or [SOURCE]},
    )


class _FakeQuerySession:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.closed = False

    async def execute(self, statement, *_args, **_kwargs):
        sql = str(statement)
        self.executed.append(sql)
        if "SET TRANSACTION" in sql.upper():
            return SimpleNamespace(fetchall=lambda: [], keys=lambda: [])
        return SimpleNamespace(
            fetchall=lambda: [("1",)],
            keys=lambda: ["value"],
        )

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_query_uses_external_session_override() -> None:
    expert = PostgresSqlExpert(llm_provider=_FakeLLM())
    session = _FakeQuerySession()
    expert._query_session_override = session
    try:
        result = await expert._run_query("SELECT 1")
    finally:
        expert._query_session_override = None

    assert result.error is None
    assert result.rows == [["1"]]
    assert any("SELECT 1" in sql for sql in session.executed)
    assert session.closed is False


@pytest.mark.asyncio
async def test_run_query_fails_closed_without_authorized_database(monkeypatch) -> None:
    expert = PostgresSqlExpert(llm_provider=_FakeLLM())
    expert._query_organization_id = ORG
    expert._query_workspace_id = WS

    async def _no_managed(*_args, **_kwargs):
        return None

    def _forbidden_internal(*_args, **_kwargs):
        raise AssertionError("no debe abrir la BD interna de ZENT")

    monkeypatch.setattr(
        "src.platform.managed_db.service.open_managed_query_session", _no_managed
    )
    monkeypatch.setattr(
        "src.infrastructure.postgres.readonly_session.get_readonly_session",
        _forbidden_internal,
    )

    result = await expert._run_query("SELECT 1")

    assert result.error is not None
    assert result.error.startswith("DATABASE_NOT_CONFIGURED")


@pytest.mark.asyncio
async def test_external_source_is_resolved_by_connector_id(monkeypatch) -> None:
    row = SimpleNamespace(
        id=uuid4(),
        name="Bodega",
        workspace_id=str(WS),
        config_json={"connector_id": str(CONNECTOR), "source_mode": "schema_only"},
        status="ready",
    )

    class _FakeSession:
        async def execute(self, *_args, **_kwargs):
            return SimpleNamespace(fetchall=lambda: [row])

        async def close(self) -> None:
            return None

    async def _session():
        return _FakeSession()

    monkeypatch.setattr(
        "src.infrastructure.postgres.session.get_async_session", _session
    )
    tool = QueryDatabaseTool(PostgresSqlExpert(llm_provider=_FakeLLM()))

    source, error = await tool._external_database_source(_context())

    assert error is None
    assert source is not None
    assert source["connector_id"] == str(CONNECTOR)
    assert source["source_mode"] == "schema_only"


@pytest.mark.asyncio
async def test_multiple_external_connectors_fail_closed(monkeypatch) -> None:
    rows = [
        SimpleNamespace(
            id=uuid4(),
            name="A",
            workspace_id=str(WS),
            config_json={"connector_id": str(CONNECTOR)},
            status="ready",
        ),
        SimpleNamespace(
            id=uuid4(),
            name="B",
            workspace_id=str(WS),
            config_json={"connector_id": str(uuid4())},
            status="ready",
        ),
    ]

    class _FakeSession:
        async def execute(self, *_args, **_kwargs):
            return SimpleNamespace(fetchall=lambda: rows)

        async def close(self) -> None:
            return None

    async def _session():
        return _FakeSession()

    monkeypatch.setattr(
        "src.infrastructure.postgres.session.get_async_session", _session
    )
    tool = QueryDatabaseTool(PostgresSqlExpert(llm_provider=_FakeLLM()))

    source, error = await tool._external_database_source(_context())

    assert source is None
    assert error is not None
    assert error.startswith("MULTIPLE_DATABASE_SOURCES")


@pytest.mark.asyncio
async def test_query_tool_routes_db_agent_to_external_executor(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class _FakeExpert:
        async def execute(self, **_kwargs):  # pragma: no cover
            raise AssertionError("no debe usar la ruta interna")

        async def execute_external(self, **kwargs):
            calls.update(kwargs)
            return SqlQueryResult(
                sql="SELECT ...",
                columns=["sku", "price", "currency"],
                rows=[["BD-ARROZ-01", "4.80", "PEN"]],
                row_count=1,
            )

    tool = QueryDatabaseTool(_FakeExpert())

    async def _source(_ctx):
        return (
            {
                "source_id": SOURCE,
                "connector_id": str(CONNECTOR),
                "workspace_id": str(WS),
                "source_mode": "schema_only",
            },
            None,
        )

    monkeypatch.setattr(tool, "_external_database_source", _source)
    result = await tool.execute(_context(), {"question": "¿Cuánto cuesta el arroz?"})

    assert result.error is None
    assert "BD-ARROZ-01" in (result.output or "")
    assert calls["connector_id"] == CONNECTOR
    assert result.meta["source_mode"] == "schema_only"


def test_preferred_catalog_view_wins_for_product_questions() -> None:
    view = DataSource(
        schema_name="bodega",
        table_name="product_catalog_v",
        columns=[
            ColumnMeta(name="sku", data_type="text", is_nullable=True),
            ColumnMeta(name="name", data_type="text", is_nullable=True),
            ColumnMeta(name="price", data_type="numeric", is_nullable=True),
            ColumnMeta(name="available", data_type="integer", is_nullable=True),
        ],
    )
    orders = DataSource(schema_name="bodega", table_name="orders")
    prefer = _preferred_catalog_source("¿Cuánto cuesta el arroz?", [view, orders])
    assert prefer == [view]

    # Una pregunta de pedidos no debe forzar la vista de catálogo.
    assert _preferred_catalog_source("¿Cómo va mi pedido?", [view, orders]) is None


def test_db_only_agent_hides_document_search() -> None:
    from src.agents.runtime.agent_runtime import _filter_tools_by_sources

    tools, omitted = _filter_tools_by_sources(
        ["search_knowledge", "query_database"],
        {"sql"},
        api_allowlist=[],
    )

    assert tools == ["query_database"]
    assert omitted == [
        {"tool": "search_knowledge", "reason": "no_knowledge_sources"}
    ]

# =============================================================================
# P19-00 — Reproducciones adversariales del baseline (solo auditoría).
#
# Estos tests describen el comportamiento ACTUAL del binder SQL. Los casos
# marcados `xfail(strict=True)` son hallazgos P0/P1: fallan contra la promesa
# de seguridad y deben convertirse en PASS al cerrar P19-01. No se corrige el
# motor en esta fase.
#
# Ningún test usa filas reales: la sesión SQL es un doble que solo registra
# el statement. Los tests de bindings usan UUIDs efímeros y limpian su fila.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from src.platform.workflows.bindings import (
    BindingError,
    _dispatch_binding,
    _execute_managed_select,
    resolve_binding,
    upsert_binding,
)

P19_01_PENDING = "P19-01 pendiente: el plan canónico del servidor aún no existe"


class _RecordedResult:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def fetchall(self) -> list[Any]:
        return self._rows


class _RecordingSession:
    """Sesión SQL falsa: registra statement y parámetros, no devuelve datos."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.closed = False
        self._rows = rows or []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _RecordedResult:
        self.statements.append(str(statement))
        self.params.append(dict(params or {}))
        return _RecordedResult(self._rows)

    async def close(self) -> None:
        self.closed = True


def _patch_query_session(monkeypatch: pytest.MonkeyPatch, session: _RecordingSession) -> None:
    import src.platform.managed_db.service as managed_service

    async def _open(*_args: Any, **_kwargs: Any) -> _RecordingSession:
        return session

    monkeypatch.setattr(managed_service, "open_managed_query_session", _open)


def _binding(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "capability_ref": "p19.audit.query",
        "provider_kind": "managed_db",
        "config": config,
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }


async def _run_select(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> _RecordingSession:
    session = _RecordingSession()
    _patch_query_session(monkeypatch, session)
    await _execute_managed_select(
        uuid4(),
        _binding(config),
        payload,
        workspace_id=uuid4(),
    )
    return session


# ---------------------------------------------------------------------------
# 1. Sustitución del recurso autorizado desde el payload
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_payload_cannot_override_binding_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _run_select(
        monkeypatch,
        {"table": "product_prices", "columns": ["sku", "price"]},
        {"table": "loyalty_balances", "columns": ["customer_id", "balance"]},
    )
    sql = session.statements[0]
    assert "FROM product_prices" in sql, f"el payload desvió el recurso: {sql}"
    assert "loyalty_balances" not in sql


# ---------------------------------------------------------------------------
# 2. SELECT * y proyección no autorizada desde el payload
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_payload_cannot_request_star_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _run_select(
        monkeypatch,
        {"table": "product_prices", "columns": ["sku", "price"]},
        {"columns": ["*"]},
    )
    sql = session.statements[0]
    assert "*" not in sql, f"el payload abrió SELECT *: {sql}"
    assert "sku" in sql and "price" in sql


# ---------------------------------------------------------------------------
# 3. Filtros obligatorios: reemplazo y operadores no permitidos
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_payload_cannot_replace_required_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _run_select(
        monkeypatch,
        {
            "table": "product_prices",
            "columns": ["sku", "price"],
            "filters": {
                "channel": {"op": "eq", "value": "retail"},
                "sku": {"op": "eq", "value": "ARR-001"},
            },
        },
        {"filters": {"sku": {"op": "eq", "value": "ATACANTE"}}},
    )
    sql = session.statements[0]
    assert "channel" in sql, f"el payload eliminó un predicado obligatorio: {sql}"
    assert session.params[0].get("f0") == "retail", session.params[0]
    assert "ATACANTE" not in sql


@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_unknown_operator_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(BindingError) as exc:
        await _run_select(
            monkeypatch,
            {"table": "orders", "columns": ["id", "status"]},
            {"filters": {"id": {"op": "union_select", "value": "x"}}},
        )
    assert exc.value.code == "INVALID_PARAMS"


# ---------------------------------------------------------------------------
# 4. Límites, orden y presupuesto por binding
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_payload_cannot_raise_binding_row_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = await _run_select(
        monkeypatch,
        {"table": "product_prices", "columns": ["sku"], "limit": 1},
        {"limit": 500},
    )
    assert "LIMIT 1" in session.statements[0], session.statements[0]


@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_payload_cannot_choose_order_by(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(BindingError):
        await _run_select(
            monkeypatch,
            {"table": "orders", "columns": ["id", "status"]},
            {"order_by": {"column": "customer_id", "dir": "desc"}},
        )


# ---------------------------------------------------------------------------
# 5. Herencia de binding y separación entre autorización e inexistencia
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason=P19_01_PENDING)
async def test_p19_00_red_org_binding_is_not_inherited_without_explicit_grant() -> None:
    from src.infrastructure.postgres.session import get_async_session

    organization_id = uuid4()
    workspace_id = uuid4()
    capability_ref = f"p19.audit.{uuid4().hex[:10]}"
    binding = await upsert_binding(
        organization_id,
        capability_ref,
        "managed_db",
        config={"table": "product_prices"},
        workspace_id=None,
    )
    try:
        resolved = await resolve_binding(organization_id, capability_ref, workspace_id=workspace_id)
        assert resolved is None, "un workspace sin concesión heredó el binding org-level"
    finally:
        session = await get_async_session()
        try:
            from sqlalchemy import text

            await session.execute(
                text("DELETE FROM workflow_capability_bindings WHERE id = :bid"),
                {"bid": UUID(binding["id"])},
            )
            await session.commit()
        finally:
            await session.close()


async def test_p19_00_asis_cross_org_binding_is_not_visible() -> None:
    """Hallazgo positivo: el lookup por organización no cruza tenants."""
    from src.infrastructure.postgres.session import get_async_session

    owner_org = uuid4()
    other_org = uuid4()
    capability_ref = f"p19.audit.{uuid4().hex[:10]}"
    binding = await upsert_binding(
        owner_org,
        capability_ref,
        "managed_db",
        config={"table": "product_prices"},
        workspace_id=None,
    )
    try:
        assert await resolve_binding(owner_org, capability_ref, workspace_id=uuid4()) is not None
        assert await resolve_binding(other_org, capability_ref, workspace_id=uuid4()) is None
    finally:
        session = await get_async_session()
        try:
            from sqlalchemy import text

            await session.execute(
                text("DELETE FROM workflow_capability_bindings WHERE id = :bid"),
                {"bid": UUID(binding["id"])},
            )
            await session.commit()
        finally:
            await session.close()


# ---------------------------------------------------------------------------
# 6. connected_db se ejecuta contra la sesión de Managed DB
# ---------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="P19-06 pendiente: no existe adaptador externo")
async def test_p19_00_red_connected_db_is_not_routed_to_managed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_managed(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append("managed_db")
        return {"rows": []}

    import src.platform.workflows.bindings as bindings_module

    monkeypatch.setattr(bindings_module, "_execute_managed_select", _fake_managed)
    binding = {
        **_binding({"table": "product_prices"}),
        "provider_kind": "connected_db",
    }
    with pytest.raises(BindingError) as exc:
        await _dispatch_binding(
            uuid4(),
            "p19.audit.query",
            binding,
            {},
            kind="connected_db",
            workspace_id=uuid4(),
            source="workflow",
            actor_id=None,
            workflow_id=None,
            run_id=None,
            instance_id=None,
            node_id=None,
        )
    assert exc.value.code == "PROVIDER_NOT_SUPPORTED"
    assert calls == []


# ---------------------------------------------------------------------------
# 7. Contrato AS-IS de query_business_data
# ---------------------------------------------------------------------------
class _Answerability:
    sources = ["managed_db"]
    answerable = True
    status = "ANSWERABLE"
    confidence_level = 0.9
    reason_codes = ["rows_found"]
    evidence_ids = ()


class _StructuredResult:
    def __init__(self) -> None:
        self.query_id = uuid4()
        self.llm_response = type("_LLM", (), {"content": "Precio confirmado"})()
        self.method = "text_to_sql"
        self.sql_query = "SELECT sku, price FROM product_prices LIMIT 1"
        self.total_latency_ms = 12.5
        self.structured_output = {
            "rows": [{"sku": "ARR-001", "price": "5.00"}],
            "columns": ["sku", "price"],
            "row_count": 1,
            "truncated": False,
        }
        self.answerability = _Answerability()
        self.retrieval_context = None
        self.lazy_ingested = False
        self.lazy_rows_indexed = 0


async def test_p19_00_asis_query_business_data_output_contract() -> None:
    """Documenta el contrato actual: expone SQL y no expone structured_output."""
    from src.api.deps import get_rag_orchestrator
    from src.api.main import app
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import (
        NodeContext,
        NodeTypeDef,
        _exec_query_business_data,
    )
    from src.platform.workflows.runtime import ExecutionContext

    fake = _StructuredResult()
    app.dependency_overrides[get_rag_orchestrator] = lambda: type(
        "_Orch", (), {"execute": staticmethod(lambda **_kwargs: _async_value(fake))}
    )()
    try:
        execution = ExecutionContext(
            organization_id=uuid4(),
            workspace_id=uuid4(),
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="user",
            trigger_type="manual",
            permissions=frozenset(),
        )
        rctx = NodeContext(
            execution=execution,
            node=WorkflowNode(
                id="q1",
                type="query_business_data",
                config={"ask": "precio del arroz"},
            ),
            node_type=NodeTypeDef(
                node_type="query_business_data",
                version=1,
                label="Consultar datos de negocio",
                category="data",
                risk_level="normal",
                capabilities=frozenset(),
            ),
            node_id="q1",
            inputs={},
            trigger={},
            payload={},
            variables={},
            node_outputs={},
            idempotency_key=None,
        )
        outcome = await _exec_query_business_data(rctx)
    finally:
        app.dependency_overrides.pop(get_rag_orchestrator, None)

    assert outcome.error is None
    output = outcome.output
    assert output["rows"] == [{"sku": "ARR-001", "price": "5.00"}]
    assert output["columns"] == ["sku", "price"]
    assert output["row_count"] == 1
    assert output["answerability"]["answerable"] is True
    assert output["sql_query"] == fake.sql_query
    assert "structured_output" not in output
    assert "provenance" not in output


async def _async_value(value: Any) -> Any:
    return value

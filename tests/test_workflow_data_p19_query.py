# =============================================================================
# P19-01 — Contrato del plan canónico de consulta (sin SQL libre).
#
# Estos tests ejercitan el binder con una sesión SQL falsa que registra el
# statement. La integración con PostgreSQL real vive en
# test_workflow_data_p19_query_integration.py.
# =============================================================================
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.platform.workflows.bindings import (
    BindingError,
    _execute_managed_select,
)


class _Row:
    def __init__(self, data: dict[str, Any]) -> None:
        self._mapping = dict(data)


class _PlanSession:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.statements: list[str] = []
        self.params: list[dict[str, Any]] = []
        self.rows = [_Row(item) for item in (rows or [])]
        self.closed = False

    async def execute(self, statement: Any, params: dict[str, Any] | None = None):
        self.statements.append(str(statement))
        self.params.append(dict(params or {}))
        return self

    def fetchall(self) -> list[_Row]:
        return self.rows

    async def close(self) -> None:
        self.closed = True


def _plan(**overrides: Any) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "schema": "zent.data.query.binding/v1",
        "scope": "workspace",
        "resource": {"schema": "public", "name": "product_prices", "kind": "view"},
        "operation": "get_one",
        "projection": ["sku", "price", "currency"],
        "allowed_columns": ["sku", "price", "currency", "channel", "customer_id"],
        "required_predicates": [{"field": "channel", "op": "eq", "source": "binding", "value": "retail"}],
        "parameters": [
            {
                "name": "sku",
                "field": "sku",
                "operator": "eq",
                "type": "string",
                "required": True,
            }
        ],
        "policy": {"max_rows": 1, "timeout_ms": 3000, "read_only": True},
        "resource_ref": "resource.catalog.product_prices",
        "column_types": {"sku": "string", "price": "number", "currency": "string"},
    }
    plan.update(overrides)
    return plan


def _binding(config: dict[str, Any], workspace_id: UUID) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "organization_id": str(uuid4()),
        "workspace_id": str(workspace_id),
        "capability_ref": "p19.query",
        "provider_kind": "managed_db",
        "config": config,
        "credential_ref": None,
        "contract_input_schema": {},
        "contract_output_schema": {},
        "status": "active",
    }


@pytest.fixture
def workspace_id() -> UUID:
    return uuid4()


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _PlanSession:
    import src.platform.managed_db.service as managed_service

    fake = _PlanSession()

    async def _open(*_args: Any, **_kwargs: Any) -> _PlanSession:
        return fake

    monkeypatch.setattr(managed_service, "open_managed_query_session", _open)
    return fake


async def _run(
    session: _PlanSession,
    workspace_id: UUID,
    config: dict[str, Any],
    payload: dict[str, Any],
    *,
    principal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _execute_managed_select(
        uuid4(),
        _binding(config, workspace_id),
        payload,
        workspace_id=workspace_id,
        principal=principal,
    )


async def test_plan_rejects_authority_fields_in_payload(session: _PlanSession, workspace_id: UUID) -> None:
    with pytest.raises(BindingError) as exc:
        await _run(
            session,
            workspace_id,
            _plan(),
            {"params": {"sku": "ARR-001"}, "table": "loyalty_balances"},
        )
    assert exc.value.code == "UNEXPECTED_PARAMETER"
    assert session.statements == []


async def test_plan_rejects_undeclared_and_missing_params(session: _PlanSession, workspace_id: UUID) -> None:
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, _plan(), {"params": {"other": "x"}})
    assert exc.value.code == "UNEXPECTED_PARAMETER"

    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, _plan(), {"params": {}})
    assert exc.value.code == "INVALID_PARAMS"


async def test_plan_keeps_required_predicate_and_parameter(session: _PlanSession, workspace_id: UUID) -> None:
    session.rows = [_Row({"sku": "ARR-001", "price": 5, "currency": "PEN"})]
    await _run(
        session,
        workspace_id,
        _plan(),
        {"params": {"sku": "ARR-001"}},
    )
    sql = session.statements[-1]
    assert "channel = :p0" in sql
    assert "sku = :p1" in sql
    assert session.params[-1] == {"p0": "retail", "p1": "ARR-001"}


async def test_plan_rejects_star_and_columns_outside_allowlist(session: _PlanSession, workspace_id: UUID) -> None:
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, _plan(projection=["*"]), {"params": {"sku": "x"}})
    assert exc.value.code == "NEEDS_CONFIGURATION"

    config = _plan(required_predicates=[])
    config["allowed_columns"] = ["sku"]
    with pytest.raises(BindingError) as exc:
        await _run(
            session,
            workspace_id,
            config,
            {"params": {"sku": "x"}},
        )
    assert exc.value.code == "NEEDS_CONFIGURATION"


async def test_plan_rejects_unknown_operator_and_identifier(session: _PlanSession, workspace_id: UUID) -> None:
    bad_op = _plan(parameters=[{"name": "sku", "field": "sku", "operator": "union_select", "type": "string"}])
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, bad_op, {"params": {"sku": "x"}})
    assert exc.value.code == "NEEDS_CONFIGURATION"

    bad_table = _plan(resource={"schema": "public", "name": "prices;drop", "kind": "view"})
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, bad_table, {"params": {"sku": "x"}})
    assert exc.value.code == "NEEDS_CONFIGURATION"


async def test_get_one_zero_rows_is_not_found(session: _PlanSession, workspace_id: UUID) -> None:
    result = await _run(session, workspace_id, _plan(), {"params": {"sku": "NOPE"}})
    assert result["status"] == "NOT_FOUND"
    assert result["found"] is False
    assert result["record"] is None
    assert result["row_count"] == 0


async def test_get_one_multiple_rows_is_multiple_matches(session: _PlanSession, workspace_id: UUID) -> None:
    session.rows = [
        _Row({"sku": "ARR-001", "price": 5, "currency": "PEN"}),
        _Row({"sku": "ARR-002", "price": 6, "currency": "PEN"}),
    ]
    result = await _run(session, workspace_id, _plan(), {"params": {"sku": "arroz"}})
    assert result["status"] == "MULTIPLE_MATCHES"
    assert result["found"] is False
    assert result["record"] is None
    assert result["row_count"] == 2
    assert result["reason_code"] == "MULTIPLE_MATCHES"


async def test_get_one_returns_typed_contract(session: _PlanSession, workspace_id: UUID) -> None:
    session.rows = [_Row({"sku": "ARR-001", "price": 5, "currency": "PEN"})]
    result = await _run(session, workspace_id, _plan(), {"params": {"sku": "ARR-001"}})
    assert result["status"] == "FOUND"
    assert result["found"] is True
    assert result["record"] == {"sku": "ARR-001", "price": 5, "currency": "PEN"}
    assert result["columns"] == [
        {"name": "sku", "type": "string", "label": "sku"},
        {"name": "price", "type": "number", "label": "price"},
        {"name": "currency", "type": "string", "label": "currency"},
    ]
    assert result["binding_ref"]
    assert result["binding_hash"]
    assert result["source_ref"] == "resource.catalog.product_prices"
    assert result["duration_ms"] >= 0
    assert result["provenance"]["provider_kind"] == "managed_db"
    assert "sql_query" not in result
    assert "sql" not in result


async def test_list_truncates_at_plan_limit(session: _PlanSession, workspace_id: UUID) -> None:
    session.rows = [
        _Row({"sku": "A", "price": 1, "currency": "PEN"}),
        _Row({"sku": "B", "price": 2, "currency": "PEN"}),
        _Row({"sku": "C", "price": 3, "currency": "PEN"}),
    ]
    config = _plan(operation="list", policy={"max_rows": 2})
    result = await _run(session, workspace_id, config, {"params": {"sku": "A"}})
    assert "LIMIT 3" in session.statements[-1]
    assert result["status"] == "FOUND"
    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert [row["sku"] for row in result["rows"]] == ["A", "B"]


async def test_count_returns_integer(session: _PlanSession, workspace_id: UUID) -> None:
    session.rows = [_Row({"row_count": 7})]
    config = _plan(operation="count")
    result = await _run(session, workspace_id, config, {"params": {"sku": "A"}})
    assert "COUNT(*)" in session.statements[-1]
    assert result["status"] == "FOUND"
    assert result["row_count"] == 7
    assert result["rows"] == []


async def test_ownership_requires_principal_and_injects_predicate(session: _PlanSession, workspace_id: UUID) -> None:
    config = _plan(
        ownership={"field": "customer_id", "principal_claim": "customer_ref"},
        parameters=[],
    )
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, config, {"params": {}})
    assert exc.value.code == "PERMISSION_DENIED"

    session.rows = [_Row({"sku": "ARR-001", "price": 5, "currency": "PEN"})]
    await _run(
        session,
        workspace_id,
        config,
        {"params": {}},
        principal={"customer_ref": "CUST-1"},
    )
    sql = session.statements[-1]
    assert "customer_id = :p1" in sql
    assert session.params[-1]["p1"] == "CUST-1"


async def test_like_pattern_is_bounded(session: _PlanSession, workspace_id: UUID) -> None:
    config = _plan(parameters=[{"name": "sku", "field": "sku", "operator": "like", "type": "string"}])
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, config, {"params": {"sku": "%arroz"}})
    assert exc.value.code == "INVALID_PARAMS"


async def test_workspace_scope_requires_workspace_binding(session: _PlanSession, workspace_id: UUID) -> None:
    binding = _binding(_plan(), workspace_id)
    binding["workspace_id"] = None
    with pytest.raises(BindingError) as exc:
        await _execute_managed_select(uuid4(), binding, {"params": {"sku": "A"}}, workspace_id=workspace_id)
    assert exc.value.code == "NEEDS_CONFIGURATION"


async def test_org_plan_allows_only_listed_workspace(session: _PlanSession, workspace_id: UUID) -> None:
    config = _plan(scope="organization", allowed_workspace_ids=[str(workspace_id)])
    binding = _binding(config, workspace_id)
    binding["workspace_id"] = None
    session.rows = [_Row({"sku": "A", "price": 1, "currency": "PEN"})]
    result = await _execute_managed_select(uuid4(), binding, {"params": {"sku": "A"}}, workspace_id=workspace_id)
    assert result["status"] == "FOUND"

    other = uuid4()
    with pytest.raises(BindingError) as exc:
        await _execute_managed_select(
            uuid4(),
            binding,
            {"params": {"sku": "A"}},
            workspace_id=other,
        )
    assert exc.value.code == "PERMISSION_DENIED"


async def test_legacy_requires_explicit_columns_and_rejects_payload_authority(
    session: _PlanSession, workspace_id: UUID
) -> None:
    with pytest.raises(BindingError) as exc:
        await _run(session, workspace_id, {"table": "product_prices"}, {})
    assert exc.value.code == "NEEDS_CONFIGURATION"

    with pytest.raises(BindingError) as exc:
        await _run(
            session,
            workspace_id,
            {"table": "product_prices", "columns": ["sku"]},
            {"table": "loyalty_balances"},
        )
    assert exc.value.code == "UNEXPECTED_PARAMETER"


async def test_legacy_select_uses_config_and_flat_projection_param(session: _PlanSession, workspace_id: UUID) -> None:
    config = {
        "table": "product_prices",
        "columns": ["sku", "price"],
        "limit": 1,
        "filters": {"channel": {"op": "eq", "value": "retail"}},
    }
    session.rows = [_Row({"sku": "A", "price": 1})]
    result = await _run(session, workspace_id, config, {"sku": "A"})
    sql = session.statements[-1]
    assert "channel = :p0" in sql
    assert "sku = :p1" in sql
    assert "LIMIT 1" in sql
    assert result["rows"] == [{"sku": "A", "price": 1}]
    assert result["table"] == "product_prices"


async def test_plan_config_is_not_mutated_by_payload(session: _PlanSession, workspace_id: UUID) -> None:
    original = _plan()
    snapshot = deepcopy(original)
    session.rows = [_Row({"sku": "A", "price": 1, "currency": "PEN"})]
    await _run(session, workspace_id, original, {"params": {"sku": "A"}})
    assert original == snapshot

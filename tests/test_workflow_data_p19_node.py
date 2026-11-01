# =============================================================================
# P19-03 — Nodo «Consultar registros» alineado al binder canónico.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.platform.workflows.ir import WorkflowNode
from src.platform.workflows.nodes import (
    NodeContext,
    NodeTypeDef,
    _exec_data_query,
    registry,
)
from src.platform.workflows.parameters import node_business_schema
from src.platform.workflows.runtime import ExecutionContext


def _ctx(config: dict, *, simulate: bool = False) -> NodeContext:
    execution = ExecutionContext(
        organization_id=uuid4(),
        workspace_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
    )
    return NodeContext(
        execution=execution,
        node=WorkflowNode(id="q", type="data_query", config=config),
        node_type=NodeTypeDef(
            node_type="data_query",
            version=1,
            label="Consultar registros",
            category="data",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id="q",
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key=None,
        simulate=simulate,
    )


def test_data_query_is_registered_and_has_business_schema() -> None:
    assert registry.get("data_query") is not None
    schema = node_business_schema("data_query")
    assert schema is not None
    assert schema.label == "Consultar registros"
    assert any(output.key == "status" for output in schema.outputs)
    assert any(parameter.key == "capability" for parameter in schema.parameters)


def test_data_query_is_available_with_connected_db_without_managed_db() -> None:
    from src.platform.workflows.node_catalog import catalog_availability

    available, reason = catalog_availability(
        registry.require("data_query"), {"managed_db": False}
    )
    assert available is True
    assert reason is None


async def test_data_query_uses_binding_output(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.platform.workflows.bindings as bindings

    calls: list[dict] = []

    async def _execute(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "provider_kind": "managed_db",
            "output": {
                "status": "FOUND",
                "found": True,
                "record": {"sku": "ARR-001", "price": "5.00"},
                "binding_ref": "b-1",
                "binding_hash": "hash",
            },
        }

    monkeypatch.setattr(bindings, "execute_binding", _execute)
    outcome = await _exec_data_query(
        _ctx(
            {
                "capability": "p19.price.lookup",
                "binding_ref": "b-1",
                "params": {"sku": "{{trigger.sku}}"},
            }
        )
    )
    # El contexto no tiene trigger; la referencia queda como texto y el binder
    # real la validaría. Aquí solo verificamos la delegación.
    assert outcome.output["status"] == "FOUND"
    assert outcome.output["found"] is True
    assert outcome.output["binding_ref"] == "b-1"
    assert outcome.output["capability"] == "p19.price.lookup"
    assert outcome.output["provider_kind"] == "managed_db"
    assert calls[0]["workspace_id"] is not None


async def test_data_query_resolves_previous_intent_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.platform.workflows.bindings as bindings

    captured: list[dict] = []

    async def _execute(*args, **kwargs):
        captured.append({"args": args, "kwargs": kwargs})
        return {
            "provider_kind": "managed_db",
            "output": {"status": "FOUND", "found": True, "binding_ref": "b-1", "record": {}},
        }

    monkeypatch.setattr(bindings, "execute_binding", _execute)
    rctx = _ctx(
        {
            "capability": "p19.price.lookup",
            "binding_ref": "b-1",
            "params": {"sku": "{{nodes.intent.output.entities.sku}}"},
        }
    )
    rctx.node_outputs = {"intent": {"output": {"entities": {"sku": "ARR-001"}}}}
    outcome = await _exec_data_query(rctx)
    assert outcome.output["status"] == "FOUND"
    assert captured[0]["args"][2] == {"params": {"sku": "ARR-001"}}


async def test_data_query_detects_binding_change(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.platform.workflows.bindings as bindings

    async def _execute(*_args, **_kwargs):
        return {
            "provider_kind": "managed_db",
            "output": {
                "status": "FOUND",
                "found": True,
                "record": {"sku": "A"},
                "binding_ref": "b-2",
            },
        }

    monkeypatch.setattr(bindings, "execute_binding", _execute)
    outcome = await _exec_data_query(_ctx({"capability": "p19.price.lookup", "binding_ref": "b-1", "params": {}}))
    assert outcome.output["status"] == "ERROR"
    assert outcome.output["reason_code"] == "BINDING_CHANGED"


async def test_data_query_maps_binding_error_to_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.platform.workflows.bindings as bindings

    async def _execute(*_args, **_kwargs):
        raise bindings.BindingError("PERMISSION_DENIED", "sin identidad")

    monkeypatch.setattr(bindings, "execute_binding", _execute)
    outcome = await _exec_data_query(_ctx({"capability": "p19.loyalty", "params": {}}))
    assert outcome.error is None
    assert outcome.output["status"] == "ERROR"
    assert outcome.output["reason_code"] == "PERMISSION_DENIED"
    assert outcome.output["found"] is False


async def test_data_query_simulation_does_not_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.platform.workflows.bindings as bindings

    async def _execute(*_args, **_kwargs):
        raise AssertionError("no debe ejecutar")

    monkeypatch.setattr(bindings, "execute_binding", _execute)
    outcome = await _exec_data_query(_ctx({"capability": "p19.price.lookup", "params": {"sku": "A"}}, simulate=True))
    assert outcome.simulated is True
    assert outcome.output["status"] == "SIMULATED"
    assert outcome.planned["kind"] == "data_query"

# =============================================================================
# Copilot V2 / Plan Compiler (commit 5) — NL → Intent → Plan → WorkflowGraph,
# validación de capabilities, resumen humano y outputs estructurados.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.copilot_v2 import (
    extract_intent_with_llm,
    heuristic_intent,
    propose_workflow,
)
from src.platform.workflows.intent import (
    ConditionGroup,
    ConditionOperator,
    PlanAction,
    PlanAnalysis,
    PlanCondition,
    PlanDataSource,
    PlanFieldRef,
    PlanRecipient,
    PlanTrigger,
    TriggerKind,
    WorkflowPlan,
)
from src.platform.workflows.ir import validate_graph
from src.platform.workflows.plan_compiler import compile_plan, compiled_plan_payload
from tests.test_workflows import _create_org, _headers, _owner_session


class FakeLLM:
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload

    async def generate(self, **_: object) -> SimpleNamespace:
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(content=content)


def _stock_plan() -> WorkflowPlan:
    return WorkflowPlan(
        name="Alerta de stock bajo",
        description="Avisa a compras cuando el stock baja de 10 unidades.",
        trigger=PlanTrigger(kind=TriggerKind.event, event_type="inventory.updated"),
        conditions=ConditionGroup(
            op="and",
            children=[
                PlanCondition(
                    field=PlanFieldRef(source="Inventario", field="stock", label="Stock disponible"),
                    operator=ConditionOperator.lt,
                    value=10,
                )
            ],
        ),
        data_sources=[
            PlanDataSource(key="Inventario", kind="database", label="Consulta de inventario"),
        ],
        actions=[
            PlanAction(
                kind="notify",
                channel="email",
                recipients=[PlanRecipient(kind="team", value="compras", label="Compras")],
                subject="Stock bajo",
                message="Hay stock bajo",
            )
        ],
        confidence=0.9,
    )


# ---------------------------------------------------------------------------
# Compilación
# ---------------------------------------------------------------------------
def test_compile_stock_plan_to_valid_graph() -> None:
    compiled = compile_plan(_stock_plan(), capabilities={})
    assert compiled.valid, [i.message for i in compiled.errors]

    types = [n.type for n in compiled.graph.nodes]
    assert types[0] == "trigger_event"
    assert "query_business_data" in types
    assert "condition" in types
    assert "notify" in types

    graph_dict = compiled.graph.to_dict()
    validate_graph(compiled.graph)

    condition = next(n for n in compiled.graph.nodes if n.type == "condition")
    rules = condition.config["rules"]
    child = rules["children"][0]
    assert child["kind"] == "condition"
    assert child["field"] == "{{nodes.data_1.output.stock}}"
    assert child["operator"] == "<"
    assert child["value"] == 10

    notify = next(n for n in compiled.graph.nodes if n.type == "notify")
    assert notify.config["channel"] == "email"
    assert notify.config["recipients"][0]["value"] == "compras"

    assert graph_dict["metadata"]["plan_compiled"] is True
    assert compiled.summary.text
    assert "stock" in compiled.summary.text.lower() or "Stock" in compiled.summary.text


def test_compile_plan_without_conditions_is_linear() -> None:
    plan = _stock_plan().model_copy(update={"conditions": None, "data_sources": []})
    compiled = compile_plan(plan, capabilities={})
    assert compiled.valid
    edge_pairs = [(e.from_node, e.to_node) for e in compiled.graph.edges]
    assert ("trigger", "action_1") in edge_pairs
    assert ("action_1", "end") in edge_pairs


def test_compile_resolves_agent_by_name() -> None:
    plan = _stock_plan().model_copy(
        update={
            "actions": [],
            "analysis": [
                PlanAnalysis(
                    kind="agent",
                    agent_name="Agente de inventario",
                    prompt="Recomienda qué hacer con el stock bajo",
                )
            ],
        }
    )
    compiled = compile_plan(
        plan,
        capabilities={"agents": {"agente de inventario": {"id": "a1", "name": "Agente de inventario"}}},
    )
    llm = next(n for n in compiled.graph.nodes if n.type == "llm")
    assert llm.config["agent_id"] == "a1"
    assert llm.config["agent_name"] == "Agente de inventario"


def test_compile_unknown_agent_is_warning_not_error() -> None:
    plan = _stock_plan().model_copy(
        update={
            "actions": [],
            "analysis": [PlanAnalysis(kind="agent", agent_name="Agente fantasma", prompt="Analiza")],
        }
    )
    compiled = compile_plan(plan, capabilities={})
    codes = {i.code for i in compiled.issues}
    assert "analysis.unknown_agent" in codes
    assert compiled.valid  # se puede publicar tras elegir el agente


def test_compile_missing_integration_action_is_error() -> None:
    plan = _stock_plan().model_copy(
        update={
            "actions": [
                PlanAction(kind="marketplace_action", action_id="acme.report", description="Reportar"),
            ]
        }
    )
    compiled = compile_plan(plan, capabilities={"actions": {}})
    assert not compiled.valid
    assert any(i.code == "action.not_installed" for i in compiled.errors)


def test_compile_unconnected_channel_is_error() -> None:
    plan = _stock_plan().model_copy(
        update={"actions": [PlanAction(kind="notify", channel="slack", message="hola")]}
    )
    compiled = compile_plan(plan, capabilities={})
    assert not compiled.valid
    assert any("Slack" in i.message for i in compiled.errors)


def test_compiled_payload_has_summary_and_graph() -> None:
    payload = compiled_plan_payload(compile_plan(_stock_plan(), capabilities={}))
    assert payload["graph"]["workflow_version"] == 2
    assert payload["summary"]["actions"]
    assert payload["valid"] is True


# ---------------------------------------------------------------------------
# Intent extraction
# ---------------------------------------------------------------------------
def test_heuristic_intent_fallback() -> None:
    intent = heuristic_intent("Cada día a las 6pm dime cómo fueron las ventas")
    assert intent.trigger.kind == TriggerKind.schedule
    assert intent.schedule is not None and intent.schedule.time == "18:00"
    assert any(a.kind == "notify" for a in intent.actions)
    assert intent.confidence < 0.5


@pytest.mark.asyncio
async def test_extract_intent_with_llm_parses_json() -> None:
    payload = {
        "name": "Aviso stock",
        "trigger": {"kind": "event", "event_type": "inventory.updated"},
        "conditions": [
            {
                "field": {"source": "Inventario", "field": "stock", "label": "Stock"},
                "operator": "lt",
                "value": 10,
            }
        ],
        "data_sources": [{"key": "Inventario", "kind": "database", "label": "Inventario"}],
        "actions": [
            {"kind": "notify", "channel": "email", "recipients": [{"kind": "team", "value": "compras"}]}
        ],
        "confidence": 0.8,
    }
    intent = await extract_intent_with_llm("avísame si el stock baja de 10", FakeLLM(payload))
    assert intent.name == "Aviso stock"
    assert intent.conditions[0].operator is ConditionOperator.lt


@pytest.mark.asyncio
async def test_extract_intent_with_llm_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        await extract_intent_with_llm("hola", FakeLLM("no soy json"))


@pytest.mark.asyncio
async def test_propose_workflow_returns_intent_plan_and_summary() -> None:
    payload = {
        "name": "Stock bajo",
        "trigger": {"kind": "event", "event_type": "inventory.updated"},
        "conditions": [
            {
                "field": {"source": "Inventario", "field": "stock", "label": "Stock"},
                "operator": "lt",
                "value": 10,
            }
        ],
        "data_sources": [{"key": "Inventario", "kind": "database", "label": "Inventario"}],
        "actions": [
            {"kind": "notify", "channel": "email", "recipients": [{"kind": "team", "value": "compras"}]}
        ],
        "confidence": 0.85,
    }
    result = await propose_workflow(uuid4(), "avísame si el stock baja de 10", provider=FakeLLM(payload))
    assert result["source"] == "llm"
    assert result["plan"] is not None
    assert result["summary"]["text"]
    assert result["must_review"] is True
    assert result["intent"]["name"] == "Stock bajo"


@pytest.mark.asyncio
async def test_propose_workflow_falls_back_to_heuristics() -> None:
    result = await propose_workflow(uuid4(), "avísame cada día las ventas", provider=FakeLLM("basura"))
    assert result["source"] == "heuristics"
    assert result["plan"] is not None
    assert result["confidence"] < 0.5


# ---------------------------------------------------------------------------
# API end-to-end: proponer → compilar → crear borrador
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_copilot_api_flow_creates_draft_workflow(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Copilot V2")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    payload = {
        "name": "Alerta de stock bajo",
        "trigger": {"kind": "event", "event_type": "inventory.updated"},
        "conditions": [
            {
                "field": {"source": "Inventario", "field": "stock", "label": "Stock disponible"},
                "operator": "lt",
                "value": 10,
            }
        ],
        "data_sources": [{"key": "Inventario", "kind": "database", "label": "Consulta de inventario"}],
        "actions": [
            {
                "kind": "notify",
                "channel": "email",
                "recipients": [{"kind": "team", "value": "compras", "label": "Compras"}],
                "subject": "Stock bajo",
                "message": "Stock bajo",
            }
        ],
        "confidence": 0.9,
    }
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLM(payload)
    try:
        proposed = await async_client.post(
            "/api/v1/workflows/copilot/intent",
            headers=h,
            json={"prompt": "Cuando el stock sea menor a 10 avisa por correo al equipo de compras"},
        )
        assert proposed.status_code == 200, proposed.text
        body = proposed.json()
        assert body["plan"] is not None
        assert body["must_review"] is True

        compiled = await async_client.post(
            "/api/v1/workflows/copilot/compile",
            headers=h,
            json={"plan": body["plan"]},
        )
        assert compiled.status_code == 200, compiled.text
        compiled_body = compiled.json()
        assert compiled_body["valid"] is True

        created = await async_client.post(
            "/api/v1/workflows",
            headers=h,
            json={
                "name": "Alerta de stock bajo",
                "trigger_type": "event",
                "graph": compiled_body["graph"],
                "workflow_version": 2,
            },
        )
        assert created.status_code == 200, created.text
        assert created.json()["workflow_id"]
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


@pytest.mark.asyncio
async def test_copilot_compile_rejects_invalid_plan(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Copilot Invalid")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    resp = await async_client.post(
        "/api/v1/workflows/copilot/compile",
        headers=_headers(org),
        json={"plan": {"name": "x"}},
    )
    assert resp.status_code == 400

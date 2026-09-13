# =============================================================================
# Condition Builder + Data Picker (commit 3) — operadores de negocio, árbol
# AND/OR anidado, resolución de referencias y sample-outputs reales.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.conditions import (
    condition_rules,
    describe_condition_tree,
    evaluate_condition_tree,
    group_rules,
    normalize_rules,
    plan_node_to_rules,
)
from src.platform.workflows.engine import _eval_condition
from src.platform.workflows.intent import (
    ConditionGroup,
    ConditionOperator,
    PlanCondition,
    PlanFieldRef,
)
from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


# ---------------------------------------------------------------------------
# Operadores
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("actual", "operator", "value", "expected"),
    [
        ("stock bajo", "contains", "bajo", True),
        ("stock bajo", "not_contains", "alto", True),
        ("MacBook", "starts_with", "Mac", True),
        ("MacBook", "ends_with", "Book", True),
        ("", "is_empty", None, True),
        ("   ", "is_empty", None, True),
        ([], "is_empty", None, True),
        ({"a": 1}, "is_empty", None, False),
        (None, "not_empty", None, False),
        ("algo", "not_empty", None, True),
        ("10", "changed", "20", True),
        ("10", "changed", "10", False),
        ("10", "changed", None, False),
        (7, "<", 10, True),
        (7, "<=", 7, True),
        (7, ">=", 8, False),
        ("x", ">", 1, False),
    ],
)
def test_eval_condition_business_operators(actual, operator, value, expected) -> None:
    assert _eval_condition(actual, operator, value) is expected


# ---------------------------------------------------------------------------
# Árbol AND/OR
# ---------------------------------------------------------------------------
def _tree() -> dict:
    return group_rules(
        "and",
        [
            condition_rules("trigger.total", ">", 20000, "Total"),
            group_rules(
                "or",
                [
                    condition_rules("trigger.es_nuevo", "==", "true", "Cliente nuevo"),
                    condition_rules("trigger.ruc", "is_empty", None, "RUC"),
                ],
            ),
        ],
    )


def test_evaluate_condition_tree_and_or_nested() -> None:
    values = {"trigger.total": 25000, "trigger.es_nuevo": "true", "trigger.ruc": "20123456789"}
    result = evaluate_condition_tree(_tree(), values.get, _eval_condition)
    assert result is True

    values_a = {"trigger.total": 25000, "trigger.es_nuevo": "false", "trigger.ruc": ""}
    assert evaluate_condition_tree(_tree(), values_a.get, _eval_condition) is True

    values_b = {"trigger.total": 100, "trigger.es_nuevo": "true", "trigger.ruc": "20"}
    assert evaluate_condition_tree(_tree(), values_b.get, _eval_condition) is False


def test_evaluate_condition_tree_empty_groups() -> None:
    assert evaluate_condition_tree(group_rules("and", []), lambda _f: None, _eval_condition) is True
    assert evaluate_condition_tree(group_rules("or", []), lambda _f: None, _eval_condition) is False


def test_describe_condition_tree_is_human_readable() -> None:
    text = describe_condition_tree(_tree())
    assert "Total es mayor que 20000" in text
    assert "(Cliente nuevo es true o RUC está vacío)" in text


def test_normalize_rules_legacy_and_new() -> None:
    legacy = normalize_rules({"field": "trigger.stock", "operator": "<", "value": 10})
    assert legacy is not None and legacy["kind"] == "condition"

    direct = normalize_rules({"rules": _tree()})
    assert direct is not None and direct["kind"] == "group"

    assert normalize_rules({}) is None


def test_plan_node_to_rules_converts_plan_group() -> None:
    group = ConditionGroup(
        op="and",
        children=[
            PlanCondition(
                field=PlanFieldRef(source="Ventas", field="total", label="Total"),
                operator=ConditionOperator.gt,
                value=20000,
            ),
            PlanCondition(
                field=PlanFieldRef(source="Cliente", field="ruc", label="RUC", ref="{{trigger.ruc}}"),
                operator=ConditionOperator.is_empty,
            ),
        ],
    )
    rules = plan_node_to_rules(group)
    assert rules["kind"] == "group" and rules["op"] == "and"
    assert rules["children"][0]["operator"] == ">"
    assert rules["children"][1]["operator"] == "is_empty"
    assert "value" not in rules["children"][1]


# ---------------------------------------------------------------------------
# Resolución de campos en el nodo condition (referencias con llaves)
# ---------------------------------------------------------------------------
def _node_context(trigger: dict, node_outputs: dict):
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef
    from src.platform.workflows.runtime import ExecutionContext

    execution = ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
    )
    return NodeContext(
        execution=execution,
        node=WorkflowNode(id="c1", type="condition"),
        node_type=NodeTypeDef(
            node_type="condition",
            version=1,
            label="Si",
            category="logic",
            risk_level="info",
            capabilities=frozenset(),
        ),
        node_id="c1",
        inputs={},
        trigger=trigger,
        payload=trigger,
        variables={},
        node_outputs=node_outputs,
        idempotency_key=None,
    )


def test_resolve_condition_field_supports_stable_refs() -> None:
    from src.platform.workflows.nodes import _resolve_condition_field

    rctx = _node_context({"stock": 3}, {"n1": {"output": {"stock": 7, "detalle": {"qty": 2}}}})
    assert _resolve_condition_field("{{nodes.n1.output.stock}}", rctx) == 7
    assert _resolve_condition_field("{{nodes.n1.output.detalle.qty}}", rctx) == 2
    assert _resolve_condition_field("trigger.stock", rctx) == 3
    assert _resolve_condition_field("literal", rctx) == "literal"


def test_resolve_condition_field_legacy_steps_map() -> None:
    from src.platform.workflows.nodes import _resolve_condition_field

    rctx = _node_context({}, {"n0": {"output": {"extracted": "abc"}}})
    rctx.legacy_index_map = {"0": "n0"}
    assert _resolve_condition_field("steps.0.output.extracted", rctx) == "abc"


# ---------------------------------------------------------------------------
# API: sample-outputs con datos reales del último run simulado
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sample_outputs_returns_last_run_nodes(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sample Outputs")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node("ask", "query_business_data", {"ask": "stock disponible"}),
            _node("notify", "notify", {"channel": "in_app", "title": "Alerta", "message": "ok"}),
        ],
        edges=[_edge("e1", "t", "ask"), _edge("e2", "ask", "notify")],
        entrypoints=["t"],
    )
    created = await async_client.post(
        "/api/v1/workflows",
        headers=h,
        json={"name": "Sample WF", "trigger_type": "webhook", "graph": graph, "workflow_version": 2},
    )
    assert created.status_code == 200, created.text
    wid = created.json()["workflow_id"]

    # Sin runs: respuesta vacía pero 200 (la UI muestra "sin datos todavía").
    empty = await async_client.get(f"/api/v1/workflows/{wid}/sample-outputs", headers=h)
    assert empty.status_code == 200, empty.text
    assert empty.json()["nodes"] == {}

    run = await async_client.post(
        f"/api/v1/workflows/{wid}/run",
        headers=h,
        json={"payload": {"message": "hola"}, "simulate": True},
    )
    assert run.status_code == 200, run.text

    samples = await async_client.get(f"/api/v1/workflows/{wid}/sample-outputs", headers=h)
    assert samples.status_code == 200, samples.text
    body = samples.json()
    assert body["run_id"]
    assert body["trigger_payload"]["message"] == "hola"
    assert "notify" in body["nodes"]
    assert body["nodes"]["notify"]["status"] == "simulated"
    assert body["nodes"]["notify"]["output"]["simulated"] is True


@pytest.mark.asyncio
async def test_sample_outputs_unknown_workflow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sample 404")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    missing = await async_client.get(
        f"/api/v1/workflows/{uuid4()}/sample-outputs", headers=_headers(org)
    )
    assert missing.status_code == 404

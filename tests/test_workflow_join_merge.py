# =============================================================================
# Cognitive Workflows — Fase 5: join/merge/filter tipados + costo con IA.
#
# Ramas con nombre, estrategias de merge, filtros multi-condición, warning de
# rama costosa y estimador con contadores IA/knowledge/cognitive.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflows import _create_org, _headers, _owner_session


def _node(nid: str, ntype: str, config: dict | None = None, **extra) -> dict:
    node: dict = {
        "id": nid,
        "type": ntype,
        "label": ntype,
        "config": config or {},
        "input_ports": [{"name": "in", "type": "json"}],
        "output_ports": [{"name": "out", "type": "json"}],
        "retry_policy": {"max_attempts": 1},
        "timeout_ms": 60_000,
        "error_policy": "fail",
    }
    node.update(extra)
    return node


def _edge(eid: str, frm: str, to: str, **extra) -> dict:
    edge: dict = {"id": eid, "from_node": frm, "from_port": "out", "to_node": to, "to_port": "in"}
    edge.update(extra)
    return edge


def _graph(nodes: list[dict], edges: list[dict], entrypoints: list[str]) -> dict:
    return {
        "workflow_version": 2,
        "nodes": nodes,
        "edges": edges,
        "variables": {},
        "entrypoints": entrypoints,
        "metadata": {},
    }


async def _run_graph(async_client: AsyncClient, org: dict, graph: dict) -> dict:
    created = await async_client.post(
        "/api/v1/workflows",
        headers={**_headers(org), "Idempotency-Key": f"jm-{uuid4().hex}"},
        json={"name": "JM", "trigger_type": "webhook", "graph": graph},
    )
    assert created.status_code == 200, created.text
    run = await async_client.post(
        f"/api/v1/workflows/{created.json()['workflow_id']}/run",
        headers={**_headers(org), "Idempotency-Key": f"jmr-{uuid4().hex}"},
        json={"payload": {}, "simulate": True},
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] in ("simulated", "succeeded"), body
    return body["result"]["structured_output"]["nodes"]


async def _setup(async_client: AsyncClient, name: str) -> dict:
    org = await _create_org(async_client, name)
    org["session"] = await _owner_session(async_client, org["organization_id"])
    return org


def _two_branches_join(*, merge_config: dict | None = None, join_config: dict | None = None) -> dict:
    nodes = [
        _node("t", "trigger_webhook"),
        _node("a", "set_variable", {"name": "ventas", "value": {"total": 54000}}, label="Ventas"),
        _node("b", "set_variable", {"name": "politica", "value": {"max": "15%"}}, label="Política"),
    ]
    edges = [_edge("e1", "t", "a"), _edge("e2", "t", "b")]
    if merge_config is not None:
        nodes.append(_node("m", "merge", merge_config, label="Decidir"))
        edges += [_edge("e3", "a", "m"), _edge("e4", "b", "m")]
    else:
        nodes.append(_node("j", "join", join_config, label="Unir"))
        edges += [_edge("e3", "a", "j"), _edge("e4", "b", "j")]
    return _graph(nodes, edges, ["t"])


@pytest.mark.asyncio
async def test_join_uses_business_branch_names(async_client: AsyncClient) -> None:
    org = await _setup(async_client, "JM Join")
    nodes = await _run_graph(async_client, org, _two_branches_join())
    output = nodes["j"]["output"]
    assert output["merged"] is True
    assert list(output["branches"]) == ["Ventas", "Política"]
    assert output["branches"]["Ventas"] == {"variable": "ventas", "value": {"total": 54000}}
    assert output["values"]["a"] == output["branches"]["Ventas"]
    assert output["branch_order"] == ["Ventas", "Política"]


@pytest.mark.asyncio
async def test_merge_first_available_default(async_client: AsyncClient) -> None:
    org = await _setup(async_client, "JM Merge")
    nodes = await _run_graph(async_client, org, _two_branches_join(merge_config={}))
    output = nodes["m"]["output"]
    assert output["strategy"] == "first_available"
    assert output["selected_from"] == "a"
    assert output["first"] == {"variable": "ventas", "value": {"total": 54000}}
    assert output["selected_label"] == "Ventas"


@pytest.mark.asyncio
async def test_merge_prefer_source_and_fallback(async_client: AsyncClient) -> None:
    org = await _setup(async_client, "JM Merge Strategy")
    nodes = await _run_graph(
        async_client,
        org,
        _two_branches_join(merge_config={"strategy": "prefer_source", "source_node_id": "b"}),
    )
    output = nodes["m"]["output"]
    assert output["selected_from"] == "b"
    assert output["selected_label"] == "Política"

    org2 = await _setup(async_client, "JM Merge Fallback")
    nodes2 = await _run_graph(
        async_client,
        org2,
        _two_branches_join(
            merge_config={"strategy": "fallback", "sources": ["missing", "b"]}
        ),
    )
    output2 = nodes2["m"]["output"]
    assert output2["strategy"] == "fallback"
    assert output2["selected_from"] == "b"


@pytest.mark.asyncio
async def test_filter_multi_conditions(async_client: AsyncClient) -> None:
    org = await _setup(async_client, "JM Filter")
    data = [
        {"producto": "A", "estado": "activo", "stock": 7},
        {"producto": "B", "estado": "activo", "stock": 3},
        {"producto": "C", "estado": "inactivo", "stock": 9},
    ]
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("v", "set_variable", {"name": "lista", "value": data}),
            _node(
                "f",
                "filter",
                {
                    "items": "{{nodes.v.output.value}}",
                    "conditions": [
                        {"field": "estado", "operator": "==", "value": "activo"},
                        {"field": "stock", "operator": ">=", "value": 5},
                    ],
                    "op": "and",
                },
            ),
        ],
        [_edge("e1", "t", "v"), _edge("e2", "v", "f")],
        ["t"],
    )
    nodes = await _run_graph(async_client, org, graph)
    output = nodes["f"]["output"]
    assert output["count"] == 1
    assert output["total"] == 3
    assert output["filtered"][0]["producto"] == "A"
    assert output["op"] == "and"
    assert len(output["conditions"]) == 2


@pytest.mark.asyncio
async def test_for_each_warns_expensive_branch() -> None:
    from src.platform.workflows.ir import WorkflowNode
    from src.platform.workflows.nodes import NodeContext, NodeTypeDef, _exec_for_each
    from src.platform.workflows.runtime import ExecutionContext

    async def _branch(branch: list[str], item):  # noqa: ANN001
        return {}

    execution = ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
    )
    rctx = NodeContext(
        execution=execution,
        node=WorkflowNode(
            id="fe",
            type="for_each",
            config={"collection": [1, 2], "max_iterations": 10, "_branch": ["b1"]},
        ),
        node_type=NodeTypeDef(
            node_type="for_each",
            version=1,
            label="Para cada",
            category="logic",
            risk_level="normal",
            capabilities=frozenset(),
        ),
        node_id="fe",
        inputs={},
        trigger={},
        payload={},
        variables={},
        node_outputs={},
        idempotency_key=None,
        run_branch=_branch,
        node_types={"b1": "llm"},
    )
    outcome = await _exec_for_each(rctx)
    assert outcome.error is None
    warnings = outcome.output["warnings"]
    assert warnings[0]["code"] == "expensive_branch"
    assert warnings[0]["nodes"] == ["b1"]
    assert outcome.output["billable_calls_estimate"] == 2


@pytest.mark.asyncio
async def test_cost_estimate_counts_ai_and_warnings() -> None:
    from src.platform.workflows.capabilities import cost_estimate

    graph = _graph(
        [
            _node("t", "trigger_event", {"event_type": "sales.closed"}),
            _node(
                "fe",
                "for_each",
                {"collection": "{{trigger.items}}", "expected_items": 50},
            ),
            _node("ask", "llm", {"agent_id": str(uuid4()), "prompt": "Analiza"}),
            _node("kb", "kb_query", {"operation": "investigate", "query": "investiga"}),
            _node("j", "join"),
        ],
        [
            _edge("e1", "t", "fe"),
            _edge("e2", "fe", "ask", from_port="out"),
            _edge("e3", "ask", "j"),
            _edge("e4", "t", "kb"),
            _edge("e5", "kb", "j"),
        ],
        ["t"],
    )
    estimate = await cost_estimate(
        uuid4(),
        graph,
        {"event_type": "sales.closed", "every_minutes": 5},
    )
    assert estimate["ai_calls_per_run"] >= 50  # agente dentro del loop
    assert estimate["cognitive_calls_per_run"] >= 1
    codes = {warning["code"] for warning in estimate["warnings"]}
    assert {"agent_inside_loop", "investigation_per_event", "high_frequency_schedule", "large_batch"} <= codes

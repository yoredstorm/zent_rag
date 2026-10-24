from __future__ import annotations

from src.platform.workflows.effect_verification import classify_effects
from src.platform.workflows.ir import WorkflowGraph, WorkflowNode
from src.platform.workflows.runtime import NodeExecution


def _graph(*nodes: WorkflowNode) -> WorkflowGraph:
    return WorkflowGraph(nodes=list(nodes))


def _simulated(planned: dict) -> NodeExecution:
    return NodeExecution(status="simulated", simulated=True, planned=planned)


def test_unpinned_external_effect_is_unverified() -> None:
    graph = _graph(WorkflowNode(id="pay", type="capability_call", label="Cobrar"))
    result = classify_effects({"pay": _simulated({"kind": "capability"})}, graph)

    assert result["level"] == "UNVERIFIED"
    assert [item["node_id"] for item in result["unverified"]] == ["pay"]
    assert result["unverified"][0]["label"] == "Cobrar"
    assert result["declared"] == []
    assert result["simulated"] == []


def test_pinned_external_effect_is_declared_not_verified() -> None:
    graph = _graph(WorkflowNode(id="pay", type="capability_call", label="Cobrar"))
    result = classify_effects({"pay": _simulated({"pinned": True})}, graph)

    assert result["level"] == "DECLARED"
    assert result["unverified"] == []
    assert [item["node_id"] for item in result["declared"]] == ["pay"]


def test_pinned_read_is_declared() -> None:
    graph = _graph(WorkflowNode(id="ask", type="llm", label="Responder"))
    result = classify_effects({"ask": _simulated({"pinned": True})}, graph)

    assert result["level"] == "DECLARED"
    assert result["unverified"] == []


def test_state_is_simulated_by_design_not_unverified() -> None:
    graph = _graph(WorkflowNode(id="state", type="state_set", label="Guardar"))
    result = classify_effects({"state": _simulated({"kind": "state"})}, graph)

    assert result["level"] == "SIMULATED"
    assert result["unverified"] == []
    assert [item["node_id"] for item in result["simulated"]] == ["state"]


def test_ai_decision_is_simulated_by_design_not_unverified() -> None:
    graph = _graph(WorkflowNode(id="decide", type="ai_decision", label="Decisión de IA"))
    result = classify_effects(
        {"decide": _simulated({"kind": "yes_no", "judge": "live_readonly"})}, graph
    )

    assert result["level"] == "SIMULATED"
    assert result["unverified"] == []
    assert [item["node_id"] for item in result["simulated"]] == ["decide"]


def test_notify_is_not_an_external_effect_without_double() -> None:
    graph = _graph(WorkflowNode(id="mail", type="notify", label="Avisar"))
    result = classify_effects({"mail": _simulated({"kind": "notification"})}, graph)

    assert result["level"] == "SIMULATED"
    assert result["unverified"] == []


def test_no_effects_is_none() -> None:
    result = classify_effects({"pay": NodeExecution(status="succeeded", simulated=False)}, _graph())

    assert result == {"level": "NONE", "unverified": [], "declared": [], "simulated": []}


def test_mixed_pinned_and_unpinned_keeps_lists_separate() -> None:
    graph = _graph(
        WorkflowNode(id="pay", type="capability_call", label="Cobrar"),
        WorkflowNode(id="http", type="api_call", label="Enviar"),
    )
    result = classify_effects(
        {
            "pay": _simulated({"pinned": True}),
            "http": _simulated({"kind": "http"}),
        },
        graph,
    )

    assert result["level"] == "UNVERIFIED"
    assert [item["node_id"] for item in result["unverified"]] == ["http"]
    assert [item["node_id"] for item in result["declared"]] == ["pay"]

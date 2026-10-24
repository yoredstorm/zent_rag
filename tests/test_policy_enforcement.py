from __future__ import annotations

from uuid import uuid4

import pytest

from src.platform.workflows.ir import WorkflowGraph
from src.platform.workflows.runtime import ExecutionContext, execute_graph
from tests.test_workflow_graph import _edge, _graph, _node, _notify_node


def _ctx(*, permissions: frozenset[str]) -> ExecutionContext:
    return ExecutionContext(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=permissions,
        simulate=True,
    )


@pytest.mark.asyncio
async def test_notify_requires_workflows_run() -> None:
    graph = _graph(
        nodes=[_notify_node("n", "P05"), {"id": "end", "type": "end", "label": "Fin"}],
        edges=[_edge("e1", "n", "end")],
        entrypoints=["n"],
    )
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset()),
        {},
        persist_execution=False,
    )
    assert result.node_executions["n"].status == "denied"
    assert "workflows:run" in (result.node_executions["n"].error or "")


@pytest.mark.asyncio
async def test_notify_allowed_with_runner_permission() -> None:
    graph = _graph(
        nodes=[_notify_node("n", "P05"), {"id": "end", "type": "end", "label": "Fin"}],
        edges=[_edge("e1", "n", "end")],
        entrypoints=["n"],
    )
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset({"workflows:run"})),
        {},
        persist_execution=False,
    )
    assert result.node_executions["n"].status == "simulated"


@pytest.mark.asyncio
async def test_role_allowlist_denies_direct_capability_call(monkeypatch) -> None:
    from src.platform.studio import roles

    agent_id = str(uuid4())
    role = {
        "schema": "zent.role/v1",
        "record_id": str(uuid4()),
        "role_id": "limited_agent",
        "version": "1.0.0",
        "status": "active",
        "name": "Limitado",
        "mission": "Solo lectura",
        "allowed_capabilities": ["search_knowledge"],
        "allowed_tools": ["search_knowledge"],
        "autonomy_level": "answer_only",
        "risk_class": "low",
    }

    async def fake_role(organization_id, requested_agent_id):  # noqa: ANN001
        return role

    monkeypatch.setattr(roles, "get_agent_role", fake_role)
    graph = _graph(
        nodes=[
            _node(
                "cap",
                "capability_call",
                {"agent_id": agent_id, "capability": "danger.write"},
            ),
            {"id": "end", "type": "end", "label": "Fin"},
        ],
        edges=[_edge("e1", "cap", "end")],
        entrypoints=["cap"],
    )
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset({"external_actions:execute", "workflows:run"})),
        {},
        persist_execution=False,
    )
    assert result.node_executions["cap"].status == "denied"
    assert "allowed_capabilities" in (result.node_executions["cap"].error or "")


def test_self_approval_is_denied_without_owner_break_glass() -> None:
    from src.platform.workflows.engine import self_approval_denied

    requester = uuid4()
    assert self_approval_denied(requester, requester)
    assert not self_approval_denied(requester, uuid4())
    assert not self_approval_denied(
        requester, requester, allow_owner_self_approval=True
    )


@pytest.mark.asyncio
async def test_wellness_never_runs_clinical_capability(monkeypatch) -> None:
    from src.platform.studio import roles

    agent_id = str(uuid4())
    role = {
        "schema": "zent.role/v1",
        "record_id": str(uuid4()),
        "role_id": "wellness_companion",
        "version": "1.0.0",
        "status": "active",
        "name": "Bienestar",
        "mission": "Acompañar sin diagnosticar",
        "allowed_capabilities": ["clinical.diagnose", "conversation.send"],
        "allowed_tools": [],
        "autonomy_level": "answer_only",
        "risk_class": "regulated",
        "human_handoff": {"triggers": ["crisis"], "destination": "emergency"},
        "safety": {
            "no_medical_diagnosis": True,
            "no_psychotherapy_claim": True,
            "crisis_escalation": True,
            "consent_required": True,
        },
    }

    async def fake_role(organization_id, requested_agent_id):  # noqa: ANN001
        return role

    monkeypatch.setattr(roles, "get_agent_role", fake_role)
    graph = _graph(
        nodes=[
            _node(
                "cap",
                "capability_call",
                {"agent_id": agent_id, "capability": "clinical.diagnose"},
            ),
            {"id": "end", "type": "end", "label": "Fin"},
        ],
        edges=[_edge("e1", "cap", "end")],
        entrypoints=["cap"],
    )
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset({"external_actions:execute", "workflows:run"})),
        {},
        persist_execution=False,
    )
    assert result.node_executions["cap"].status == "denied"
    assert "clínic" in (result.node_executions["cap"].error or "").lower()

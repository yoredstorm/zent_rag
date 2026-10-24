from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.composition import (
    TYPED_PORTS,
    CompositionError,
    decide_adaptive,
    fanout_plan,
    prepare_subworkflow_call,
    saga_compensation_plan,
    subflow_definition,
    subflow_library,
)
from src.platform.workflows.error_contract import (
    error_contract,
    port_for_failure,
    port_for_message,
    typed_port_for_decision,
)
from src.platform.workflows.ir import WorkflowGraph
from src.platform.workflows.runtime import ExecutionContext, execute_graph
from tests.test_workflow_graph import _edge, _graph, _notify_node
from tests.test_workflows import _create_org, _headers, _owner_session


def _proposal(route: str, transition: str, confidence: float = 0.9) -> dict:
    return {
        "route": route,
        "confidence": confidence,
        "rationale_summary": "propuesta",
        "missing_information": [],
        "recommended_next_action": route,
        "allowed_transition_id": transition,
    }


def test_typed_ports_are_the_stable_contract() -> None:
    assert TYPED_PORTS == (
        "success",
        "not_found",
        "invalid_input",
        "timeout",
        "retryable_error",
        "unauthorized",
        "needs_human",
        "compensated",
    )
    assert port_for_failure("knowledge_not_found") == "not_found"
    assert port_for_failure("contract_mismatch") == "invalid_input"
    assert port_for_failure("timeout") == "timeout"
    assert port_for_failure("provider_unavailable") == "retryable_error"
    assert port_for_failure("unauthorized_tool") == "unauthorized"
    assert port_for_failure("human_requested") == "needs_human"
    assert typed_port_for_decision("transition") == "success"
    assert typed_port_for_decision("compensation") == "compensated"
    assert typed_port_for_decision("clarification") == "invalid_input"
    contract = error_contract("timeout", "tardó")
    assert contract["typed_port"] == "timeout"
    assert contract["retryable"] is True
    assert contract["requires_human"] is False


@pytest.mark.asyncio
async def test_runtime_denial_exposes_unauthorized_typed_port() -> None:
    graph = _graph(
        nodes=[_notify_node("n", "P07"), {"id": "end", "type": "end", "label": "Fin"}],
        edges=[_edge("e1", "n", "end")],
        entrypoints=["n"],
    )
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        ExecutionContext(
            organization_id=uuid4(),
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="user",
            trigger_type="manual",
            permissions=frozenset(),
            simulate=True,
        ),
        {},
        persist_execution=False,
    )
    execution = result.node_executions["n"]
    assert execution.status == "denied"
    assert execution.output["typed_port"] == "unauthorized"
    assert execution.output["error_contract"]["requires_human"] is True
    assert port_for_message("permiso insuficiente") == "unauthorized"


def test_adaptive_decisions_expose_typed_ports() -> None:
    allowed = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento"),
        allowlist=[
            {
                "id": "consultar_conocimiento",
                "capability_ref": "node.kb_query",
                "stage": "capability_execution",
            }
        ],
        registry_refs={"node.kb_query"},
    )
    assert allowed["typed_port"] == "success"
    timeout = decide_adaptive(
        None,
        allowlist=[],
        registry_refs=set(),
        failure_mode="timeout",
    )
    assert timeout["typed_port"] == "timeout"
    human = decide_adaptive(
        None,
        allowlist=[],
        registry_refs=set(),
        failure_mode="human_requested",
    )
    assert human["typed_port"] == "needs_human"
    unauthorized = decide_adaptive(
        _proposal("payments.checkout.create", "cobrar"),
        allowlist=[
            {
                "id": "cobrar",
                "capability_ref": "payments.checkout.create",
                "stage": "capability_execution",
            }
        ],
        registry_refs=set(),
    )
    assert unauthorized["typed_port"] in {"invalid_input", "needs_human"}
    compensated = decide_adaptive(
        None,
        allowlist=[
            {
                "id": "revertir",
                "capability_ref": "payments.checkout.refund",
                "stage": "compensation",
            }
        ],
        registry_refs={"payments.checkout.refund"},
        failure_mode="contract_mismatch",
        on_contract_mismatch="compensate",
    )
    assert compensated["decision"] == "compensation"
    assert compensated["typed_port"] == "compensated"


def test_subflow_definition_is_published_versioned_and_draft_is_blocked() -> None:
    definition = subflow_definition("consultar_conocimiento", version=2)
    assert definition.status == "published"
    assert definition.version == 2
    assert definition.public()["node_config"]["snapshot"]["status"] == "published"
    snapshot = definition.snapshot()
    assert snapshot["output_ports"] == list(TYPED_PORTS)
    prepared = prepare_subworkflow_call(
        definition.node_config(),
        parent_permissions=frozenset(),
    )
    assert prepared["status"] == "published"
    assert prepared["max_fanout"] == 10

    draft = subflow_definition("consultar_conocimiento", status="draft")
    with pytest.raises(CompositionError) as rejected:
        prepare_subworkflow_call(
            draft.node_config(),
            parent_permissions=frozenset(),
        )
    assert rejected.value.code == "contract_mismatch"
    assert "published" in rejected.value.message


def test_durable_subflow_is_explicitly_blocked_inline() -> None:
    definition = subflow_definition("solicitar_aprobacion")
    assert definition.durable is True
    with pytest.raises(CompositionError) as blocked:
        prepare_subworkflow_call(
            definition.node_config(),
            parent_permissions=frozenset(),
        )
    assert blocked.value.code == "contract_mismatch"
    assert "WAIT" in blocked.value.message or "aprobación" in blocked.value.message


def test_subflow_library_marks_durable_and_runnable() -> None:
    library = {item["name"]: item for item in subflow_library()}
    assert library["consultar_conocimiento"]["runnable_inline"] is True
    assert library["solicitar_aprobacion"]["durable"] is True
    assert library["solicitar_aprobacion"]["runnable_inline"] is False
    assert "success" in library["consultar_conocimiento"]["output_ports"]


def test_fanout_and_depth_limits_fail_closed() -> None:
    plan = fanout_plan(list(range(50)), max_fanout=20)
    assert len(plan["items"]) == 20
    assert plan["dropped"] == 30
    assert plan["truncated"] is True
    with pytest.raises(CompositionError):
        fanout_plan([1], max_fanout=21)
    definition = subflow_definition("consultar_conocimiento")
    config = definition.node_config()
    config["max_fanout"] = 21
    with pytest.raises(CompositionError):
        prepare_subworkflow_call(config, parent_permissions=frozenset())


def test_saga_compensates_in_reverse_order() -> None:
    plan = saga_compensation_plan(
        [
            {"capability_ref": "payments.checkout.create", "business_id": "order-1"},
            {"capability_ref": "inventory.reserve", "business_id": "order-1"},
        ]
    )
    assert plan["typed_port"] == "compensated"
    assert [step["capability_ref"] for step in plan["steps"]] == [
        "inventory.reserve",
        "payments.checkout.create",
    ]
    assert len({step["idempotency_key"] for step in plan["steps"]}) == 2


@pytest.mark.asyncio
async def test_subflow_library_api_requires_auth_and_returns_published(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, f"P07 Library {uuid4().hex[:6]}")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await async_client.get(
        "/api/v1/workflows/subflows/library", headers=_headers(org)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["executor"] == "execute_graph"
    assert body["subflows"]
    assert all(item["status"] == "published" for item in body["subflows"])
    assert any(item["durable"] for item in body["subflows"])

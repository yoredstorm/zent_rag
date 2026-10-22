# Contrato subworkflow.call/v1 y router adaptativo sobre el motor único.
from __future__ import annotations

from uuid import uuid4

import pytest

from src.platform.workflows.composition import (
    PORTABLE_SUBFLOWS,
    CompositionError,
    apply_seller_product_change,
    business_effect_key,
    claim_effect,
    commit_effect,
    decide_adaptive,
    engine_inventory,
    freeze_snapshot,
    inherit_permissions,
    is_nestable,
    portable_subflow,
    prepare_subworkflow_call,
    resume_definition,
    route_auditor,
    route_mentor,
    route_support,
    route_wellness,
)
from src.platform.workflows.ir import WorkflowGraph, validate_graph
from src.platform.workflows.runtime import ExecutionContext, execute_graph


def _proposal(route: str, transition: str, confidence: float = 0.91, missing: list | None = None) -> dict:
    return {
        "route": route,
        "confidence": confidence,
        "rationale_summary": "propuesta",
        "missing_information": list(missing or []),
        "recommended_next_action": route,
        "allowed_transition_id": transition,
    }


def _allow_kb() -> list[dict]:
    return [
        {
            "id": "consultar_conocimiento",
            "capability_ref": "node.kb_query",
            "stage": "capability_execution",
        }
    ]


def _ctx(**kwargs) -> ExecutionContext:
    base = dict(
        organization_id=uuid4(),
        workflow_id=uuid4(),
        run_id=uuid4(),
        actor_type="user",
        trigger_type="manual",
        permissions=frozenset(),
        simulate=True,
    )
    base.update(kwargs)
    return ExecutionContext(**base)


def _child_graph() -> dict:
    return {
        "workflow_version": 2,
        "nodes": [
            {"id": "start", "type": "trigger_event", "label": "Inicio"},
            {"id": "end", "type": "end", "label": "Fin"},
        ],
        "edges": [
            {
                "id": "e",
                "from_node": "start",
                "from_port": "out",
                "to_node": "end",
                "to_port": "in",
            }
        ],
        "entrypoints": ["start"],
    }


def test_inventory_uses_the_existing_engine() -> None:
    inventory = engine_inventory()
    assert inventory["executor"] == "execute_graph"
    assert inventory["parallel_runtime"] is False
    assert "wait_event" in inventory["handlers"]
    assert "loop" in inventory["handlers"]
    assert "subworkflow_call" in inventory["handlers"]
    assert "adaptive_route" in inventory["handlers"]
    assert inventory["loop_wait"]["wait_releases_worker"] is True
    assert inventory["loop_wait"]["snapshot"] == "definition_snapshot"


def test_resume_uses_frozen_snapshot_not_live_graph() -> None:
    frozen = _child_graph()
    live = {"nodes": [{"id": "LIVE"}], "edges": [], "entrypoints": ["LIVE"]}
    graph = resume_definition({"definition_snapshot": {"graph": frozen}}, live)
    assert graph["nodes"][0]["id"] == "start"
    with pytest.raises(CompositionError) as exc:
        resume_definition({"definition_snapshot": {}}, live)
    assert exc.value.code == "contract_mismatch"


def test_permissions_are_never_expanded() -> None:
    assert inherit_permissions(frozenset({"a"}), frozenset({"a", "b"})) == frozenset({"a"})
    assert inherit_permissions(frozenset({"a", "b"}), None) == frozenset({"a", "b"})


def test_subworkflow_rejects_live_version_cycles_depth_and_unknown_capabilities() -> None:
    snapshot = freeze_snapshot(_child_graph(), 2, workflow_ref="consultar_conocimiento")
    with pytest.raises(CompositionError) as live:
        prepare_subworkflow_call(
            {"resolve": "live", "workflow_ref": "consultar_conocimiento", "version": 2},
            parent_permissions=frozenset(),
        )
    assert live.value.code == "contract_mismatch"
    prepared = prepare_subworkflow_call(
        {
            "workflow_ref": "consultar_conocimiento",
            "snapshot": snapshot,
            "registry_refs": [],
            "idempotency_key": "once",
            "permissions": ["a", "secret"],
            "max_retries": 2,
        },
        parent_permissions=frozenset({"a"}),
    )
    assert prepared["version"] == 2
    assert prepared["dropped_permissions"] == ["secret"]
    assert prepared["effective_permissions"] == ["a"]
    with pytest.raises(CompositionError):
        prepare_subworkflow_call(
            {
                "workflow_ref": "consultar_conocimiento",
                "snapshot": snapshot,
                "registry_refs": [],
                "idempotency_key": "once",
            },
            parent_permissions=frozenset(),
            stack=["consultar_conocimiento"],
        )
    with pytest.raises(CompositionError):
        prepare_subworkflow_call(
            {
                "workflow_ref": "consultar_conocimiento",
                "snapshot": snapshot,
                "registry_refs": [],
                "idempotency_key": "once",
                "max_depth": 1,
            },
            parent_permissions=frozenset(),
            depth=1,
        )
    child = portable_subflow("cobrar_pedido")
    charged = freeze_snapshot(child, 1, workflow_ref="cobrar_pedido")
    with pytest.raises(CompositionError) as unknown:
        prepare_subworkflow_call(
            {
                "workflow_ref": "cobrar_pedido",
                "snapshot": charged,
                "registry_refs": [],
                "idempotency_key": "pay-1",
            },
            parent_permissions=frozenset(),
        )
    assert unknown.value.code == "unauthorized_tool"
    with pytest.raises(CompositionError):
        prepare_subworkflow_call(
            {
                "workflow_ref": "preguntar_aclaracion",
                "snapshot": freeze_snapshot(
                    portable_subflow("preguntar_aclaracion"), 1, workflow_ref="preguntar_aclaracion"
                ),
                "registry_refs": [],
                "idempotency_key": "ask-1",
            },
            parent_permissions=frozenset(),
        )


def test_payment_effect_replays_instead_of_running_twice() -> None:
    key = business_effect_key("payments.checkout.create", "order-9")
    ledger: dict = {}
    assert claim_effect(ledger, key)["action"] == "run"
    commit_effect(ledger, key, "applied", {"charge_id": "c1"})
    replay = claim_effect(ledger, key)
    assert replay["action"] == "replay"
    assert replay["output"]["charge_id"] == "c1"
    commit_effect(ledger, "half", "incomplete", None)
    assert claim_effect(ledger, "half")["action"] == "blocked"


def test_router_does_not_execute_unannounced_or_low_confidence_routes() -> None:
    allowed = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento"),
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
    )
    assert allowed["decision"] == "transition"
    assert allowed["execute_capability"] is True
    assert allowed["port"] == "consultar_conocimiento"
    assert allowed["capability_ref"] == "node.kb_query"
    for field in (
        "route",
        "confidence",
        "rationale_summary",
        "missing_information",
        "recommended_next_action",
        "allowed_transition_id",
    ):
        assert field in allowed

    hidden = decide_adaptive(
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
    assert hidden["execute_capability"] is False
    assert hidden["decision"] == "halt"
    assert hidden["failure_mode"] == "contract_mismatch"

    unsure = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento", confidence=0.2),
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
        guard={"warning": True, "allowed": True},
    )
    assert unsure["decision"] == "clarification"
    assert unsure["execute_capability"] is False
    assert "No entendí" not in unsure["message"]
    plain = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento", confidence=0.2),
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
    )
    assert plain["message"] != unsure["message"]

    missing = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento", missing=["talla"]),
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
    )
    assert missing["decision"] == "clarification"
    assert missing["failure_mode"] == "missing_data"
    assert missing["execute_capability"] is False

    blocked = decide_adaptive(
        _proposal("consultar_conocimiento", "consultar_conocimiento", confidence=0.1),
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
        guard={"blocked": True},
    )
    assert blocked["decision"] == "intervention"

    cancelled = decide_adaptive(
        None,
        allowlist=_allow_kb(),
        registry_refs={"node.kb_query"},
        failure_mode="user_cancelled",
    )
    assert cancelled["control"] == "stop_success"
    assert cancelled["execute_capability"] is False


def test_seller_keeps_cart_and_payment_key_while_waiting() -> None:
    from src.platform.workflows.instances import _loop_body

    state = {
        "cart": [{"sku": "arroz", "qty": 1}],
        "order_id": "order-9",
        "business_key": "conv-1",
        "conversation_id": "conv-1",
    }
    changed = apply_seller_product_change(state, "fideos")
    assert changed["cart"] == [{"sku": "arroz", "qty": 1}]
    assert changed["state"]["pending_product"] == "fideos"
    assert changed["payment_effect_key"] == business_effect_key("payments.checkout.create", "order-9")
    again = apply_seller_product_change(changed["state"], "azúcar")
    assert again["payment_effect_key"] == changed["payment_effect_key"]
    assert again["process_key"] == "conv-1"
    body = _loop_body(
        {
            "edges": [
                {"from_node": "save_cart", "to_node": "search"},
                {"from_node": "search", "to_node": "loop"},
                {"from_node": "loop", "to_node": "search"},
            ]
        },
        "search",
        "loop",
    )
    assert "save_cart" not in body
    assert "search" in body


def test_mentor_changes_goal_without_inventing_evaluation() -> None:
    state = {"goal": "sumas", "progress": {"done": 2}}
    turned = route_mentor(
        state,
        "restas",
        {"source": "capability", "next_exercise": "resta-1", "capability_ref": "learning.progress.get"},
        {"source": "llm", "score": 10},
    )
    assert turned["state"]["goal"] == "restas"
    assert turned["progress_kept"] == {"done": 2}
    assert turned["next_exercise"] == "resta-1"
    assert turned["evaluation"]["accepted"] is False
    verified = route_mentor(
        state,
        None,
        {"source": "llm", "next_exercise": "inventado"},
        {"source": "capability", "score": 4, "capability_ref": "learning.exercise.evaluate"},
    )
    assert verified["evaluation"]["accepted"] is True
    assert verified["evaluation"]["score"] == 4
    assert verified["next_exercise"] is None


def test_support_uses_kb_case_or_handoff() -> None:
    proposal = _proposal("consultar_conocimiento", "consultar_conocimiento")
    kb = route_support(
        proposal,
        registry_refs={"node.kb_query", "support.case.open", "subflow.escalar_humano"},
        permissions=frozenset({"support:case"}),
    )
    assert kb["decision"] == "transition"
    assert kb["capability_ref"] == "node.kb_query"

    case = route_support(
        proposal,
        registry_refs={"support.case.open", "subflow.escalar_humano"},
        permissions=frozenset({"support:case"}),
    )
    assert case["decision"] == "transition"
    assert case["capability_ref"] == "support.case.open"
    assert case["execute_capability"] is True

    handoff = route_support(
        proposal,
        registry_refs={"support.case.open", "subflow.escalar_humano"},
        permissions=frozenset(),
    )
    assert handoff["decision"] == "intervention"
    assert handoff["execute_capability"] is False
    assert handoff["handoff"]["purpose"] == "derivar soporte"
    assert "other_user" not in handoff["handoff"]["context"]


def test_auditor_waits_for_approval_when_evidence_conflicts() -> None:
    evidence = {"finding_id": "f-1", "other_user_note": "secreto"}
    decision = route_auditor(
        incongruent=True,
        evidence=evidence,
        registry_refs={"subflow.solicitar_aprobacion"},
    )
    assert decision["decision"] == "wait"
    assert decision["execute_capability"] is False
    assert decision["evidence"]["finding_id"] == "f-1"
    assert decision["handoff"]["context"] == {"finding_id": "f-1"}
    assert "other_user_note" not in decision["handoff"]["context"]


def test_wellness_does_not_diagnose_or_store_sensitive_data() -> None:
    state = {"locale": "es", "symptoms": "dato clínico", "other_user_note": "ajeno"}
    calm = route_wellness(
        "quiero dormir mejor",
        state,
        _proposal("conversar", "conversar"),
        registry_refs={"conversation.reply", "subflow.escalar_humano", "clinical.diagnose"},
        consent=False,
    )
    assert calm["decision"] == "transition"
    assert calm["capability_ref"] == "conversation.reply"
    assert calm["diagnosis"] is None
    assert "symptoms" not in calm["stored_state"]

    crisis = route_wellness(
        "no quiero vivir",
        state,
        _proposal("conversar", "conversar"),
        registry_refs={"conversation.reply", "clinical.diagnose"},
        consent=False,
    )
    assert crisis["decision"] == "intervention"
    assert crisis["execute_capability"] is False
    assert crisis["diagnosis"] is None
    assert crisis["handoff"]["context"] == {"locale": "es"}
    assert "symptoms" not in crisis["stored_state"]


def test_portable_subflows_validate_and_nest_only_without_wait() -> None:
    for name in PORTABLE_SUBFLOWS:
        validate_graph(WorkflowGraph.from_dict(portable_subflow(name)))
    assert is_nestable("cobrar_pedido")
    assert is_nestable("evaluar_ejercicio")
    assert is_nestable("consultar_conocimiento")
    assert is_nestable("identificar_intencion")
    assert is_nestable("registrar_progreso")
    assert not is_nestable("preguntar_aclaracion")
    assert not is_nestable("solicitar_aprobacion")
    assert not is_nestable("escalar_humano")
    kinds = {node["type"] for node in portable_subflow("evaluar_ejercicio")["nodes"]}
    assert "llm" not in kinds
    assert "capability_call" in kinds


async def test_runtime_runs_only_the_authorized_transition() -> None:
    route = {
        "id": "route",
        "type": "adaptive_route",
        "label": "Router",
        "config": {
            "registry_refs": ["payments.checkout.create"],
            "allowlist": [
                {
                    "id": "cobrar",
                    "capability_ref": "payments.checkout.create",
                    "stage": "capability_execution",
                }
            ],
            "proposal": _proposal("cobrar", "cobrar"),
        },
        "output_ports": [
            {"name": "cobrar", "type": "json"},
            {"name": "clarify", "type": "json"},
            {"name": "halt", "type": "json"},
        ],
    }
    graph = {
        "workflow_version": 2,
        "nodes": [
            {"id": "start", "type": "trigger_event", "label": "Inicio"},
            route,
            {
                "id": "pay",
                "type": "capability_call",
                "label": "Cobrar",
                "config": {"capability": "payments.checkout.create"},
            },
            {
                "id": "evil",
                "type": "capability_call",
                "label": "Otra",
                "config": {"capability": "other.tool"},
            },
            {"id": "end", "type": "end", "label": "Fin"},
        ],
        "edges": [
            {"id": "e1", "from_node": "start", "from_port": "out", "to_node": "route", "to_port": "in"},
            {"id": "e2", "from_node": "route", "from_port": "cobrar", "to_node": "pay", "to_port": "in"},
            {"id": "e3", "from_node": "route", "from_port": "clarify", "to_node": "evil", "to_port": "in"},
            {"id": "e4", "from_node": "pay", "from_port": "out", "to_node": "end", "to_port": "in"},
            {"id": "e5", "from_node": "evil", "from_port": "out", "to_node": "end", "to_port": "in"},
        ],
        "entrypoints": ["start"],
    }
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset({"external_actions:execute"})),
        {},
    )
    assert result.status == "succeeded"
    assert result.node_executions["pay"].status == "simulated"
    assert result.node_executions["pay"].output["capability"] == "payments.checkout.create"
    assert result.node_executions["evil"].status == "skipped"


async def test_runtime_blocks_a_transition_to_a_different_capability() -> None:
    graph = {
        "workflow_version": 2,
        "nodes": [
            {"id": "start", "type": "trigger_event", "label": "Inicio"},
            {
                "id": "route",
                "type": "adaptive_route",
                "label": "Router",
                "config": {
                    "registry_refs": ["payments.checkout.create"],
                    "allowlist": [
                        {
                            "id": "cobrar",
                            "capability_ref": "payments.checkout.create",
                            "stage": "capability_execution",
                        }
                    ],
                    "proposal": _proposal("cobrar", "cobrar"),
                },
                "output_ports": [{"name": "cobrar", "type": "json"}, {"name": "halt", "type": "json"}],
            },
            {
                "id": "evil",
                "type": "capability_call",
                "label": "Otra",
                "config": {"capability": "other.tool"},
            },
        ],
        "edges": [
            {"id": "e1", "from_node": "start", "from_port": "out", "to_node": "route", "to_port": "in"},
            {"id": "e2", "from_node": "route", "from_port": "cobrar", "to_node": "evil", "to_port": "in"},
        ],
        "entrypoints": ["start"],
    }
    result = await execute_graph(WorkflowGraph.from_dict(graph), _ctx(), {})
    assert result.status == "failed"
    assert result.node_executions["evil"].status == "failed"
    assert result.node_executions["evil"].output["failure_mode"] == "unauthorized_tool"
    assert result.node_executions["evil"].output["execute_capability"] is False


async def test_subworkflow_simulate_freezes_snapshot_and_refuses_live() -> None:
    snapshot = freeze_snapshot(_child_graph(), 4, workflow_ref="consultar_conocimiento")
    graph = {
        "workflow_version": 2,
        "nodes": [
            {"id": "start", "type": "trigger_event", "label": "Inicio"},
            {
                "id": "child",
                "type": "subworkflow_call",
                "label": "Hijo",
                "config": {
                    "workflow_ref": "consultar_conocimiento",
                    "snapshot": snapshot,
                    "registry_refs": [],
                    "idempotency_key": "snap-1",
                    "permissions": ["secret"],
                },
            },
        ],
        "edges": [
            {"id": "e1", "from_node": "start", "from_port": "out", "to_node": "child", "to_port": "in"}
        ],
        "entrypoints": ["start"],
    }
    result = await execute_graph(
        WorkflowGraph.from_dict(graph),
        _ctx(permissions=frozenset({"read"})),
        {},
    )
    assert result.status == "succeeded"
    output = result.node_executions["child"].output
    assert output["snapshot_hash"] == snapshot["snapshot_hash"]
    assert output["workflow_version"] == 4
    assert output["dropped_permissions"] == ["secret"]
    assert output["effective_permissions"] == []

    live = {
        "workflow_version": 2,
        "nodes": [
            {"id": "start", "type": "trigger_event", "label": "Inicio"},
            {
                "id": "child",
                "type": "subworkflow_call",
                "label": "Vivo",
                "config": {"resolve": "live", "workflow_ref": "consultar_conocimiento", "version": 9},
            },
        ],
        "edges": [
            {"id": "e1", "from_node": "start", "from_port": "out", "to_node": "child", "to_port": "in"}
        ],
        "entrypoints": ["start"],
    }
    refused = await execute_graph(WorkflowGraph.from_dict(live), _ctx(), {})
    assert refused.status == "failed"
    assert "viva" in (refused.node_executions["child"].error or "")

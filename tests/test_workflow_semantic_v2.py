# =============================================================================
# Prompt 04 — Semantic Compiler Enterprise.
#
# Pruebas de contrato v2, referencias/tipos, WAIT/LOOP/estado durable,
# capability_call, agente, aprobación, compensación y evolución de capacidad.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.platform.workflows.architect_compiler import compile_semantic_plan
from src.platform.workflows.architect_models import SemanticPlan, normalize_semantic_plan
from src.platform.workflows.architect_validator import validate_semantic_plan
from src.platform.workflows.ir import WorkflowGraph, validate_graph

_PERMS = frozenset(
    {
        "workflows:read",
        "workflows:create",
        "external_actions:execute",
        "agents:execute",
    }
)


def _capability(
    ref: str,
    *,
    inputs: dict | None = None,
    outputs: dict | None = None,
    required_inputs: list[str] | None = None,
    version: int = 1,
    side_effects: list[str] | None = None,
    risk: str = "normal",
    permissions: list[str] | None = None,
) -> dict:
    return {
        "capability_ref": ref,
        "version": version,
        "required_inputs": required_inputs or [],
        "availability": {"status": "AVAILABLE", "executable": True, "reasons": []},
        "required_permissions": permissions or [],
        "input_schema": {"type": "object", "properties": inputs or {}},
        "output_schema": {"type": "object", "properties": outputs or {}},
        "side_effects": side_effects or ["read"],
        "risk_level": risk,
        "contract_hash": f"hash-{ref}-v{version}",
        "provider_kind": "internal",
        "source": "commerce",
        "idempotency_policy": {"strategy": "instance_node"},
    }


def _caps() -> dict:
    index = {
        "catalog.products.search": _capability(
            "catalog.products.search",
            inputs={"query": {"type": "string"}},
            outputs={
                "products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "price": {"type": "number"},
                        },
                    },
                }
            },
            required_inputs=["query"],
        ),
        "inventory.stock.get": _capability(
            "inventory.stock.get",
            inputs={"sku": {"type": "string"}},
            outputs={"stock": {"type": "number"}},
            required_inputs=["sku"],
        ),
        "inventory.reserve": _capability(
            "inventory.reserve",
            inputs={"sku": {"type": "string"}, "quantity": {"type": "integer"}},
            outputs={"reservation_id": {"type": "string"}},
            required_inputs=["sku", "quantity"],
            side_effects=["write"],
        ),
        "orders.get": _capability(
            "orders.get",
            inputs={"order_id": {"type": "string"}},
            outputs={"order_id": {"type": "string"}, "status": {"type": "string"}},
            required_inputs=["order_id"],
        ),
        "payments.charge": _capability(
            "payments.charge",
            inputs={"amount": {"type": "number"}},
            outputs={"payment_id": {"type": "string"}},
            required_inputs=["amount"],
            side_effects=["financial", "external"],
            risk="critical",
        ),
        "payments.refund": _capability(
            "payments.refund",
            inputs={"payment_id": {"type": "string"}},
            outputs={"refund_id": {"type": "string"}},
            required_inputs=["payment_id"],
            side_effects=["financial", "external"],
            risk="critical",
        ),
    }
    return {
        "available": {"managed_db": True, "agents": True, "knowledge_bases": False},
        "agents": [
            {
                "id": "a1",
                "name": "Analista",
                "purpose": "Analizar evidencia",
                "tools": [],
                "knowledge_base_ids": [],
                "source_ids": [],
                "output_schema": True,
            }
        ],
        "knowledge_bases": [],
        "actions": {},
        "events": ["conversation.message", "payment.succeeded"],
        "permissions": sorted(_PERMS),
        "capability_index": index,
    }


def _compile(plan: dict, *, permissions: frozenset[str] = _PERMS) -> tuple[SemanticPlan, dict]:
    semantic = normalize_semantic_plan(SemanticPlan.model_validate(plan))
    issues = validate_semantic_plan(semantic, _caps(), permissions=permissions)
    result = compile_semantic_plan(semantic, _caps())
    return semantic, {"issues": issues, "compiled": result}


def _graph_ok(result: dict) -> None:
    assert result["graph"] is not None
    validate_graph(WorkflowGraph.from_dict(result["graph"]))


def _node_by_step(result: dict, step_id: str) -> dict:
    return next(
        node
        for node in result["graph"]["nodes"]
        if node["metadata"]["architect"]["step_id"] == step_id
    )


def _simple_plan(*, schema_version: str | None = None) -> dict:
    plan = {
        "goal": "Buscar productos y avisar",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Buscar productos",
                "depends_on": ["t"],
                "params": {
                    "capability": "catalog.products.search",
                    "inputs": {"query": "arroz"},
                },
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Avisar",
                "depends_on": ["c"],
                "params": {"channel": "in_app", "title": "Productos", "message": "Listo"},
            },
        ],
    }
    if schema_version:
        plan["schema_version"] = schema_version
    return plan


def test_v1_plan_adapter_upgrades_to_v2_without_mutating_original() -> None:
    original = SemanticPlan.model_validate(_simple_plan())
    assert original.schema_version == "1.0"
    upgraded = normalize_semantic_plan(original)
    assert upgraded.schema_version == "2.0"
    assert original.schema_version == "1.0"
    compiled = compile_semantic_plan(upgraded, _caps())
    assert compiled["graph"]["metadata"]["plan_schema_version"] == "2.0"
    _graph_ok(compiled)


def test_linear_capability_compiles_as_internal_not_marketplace() -> None:
    _semantic, result = _compile(_simple_plan(schema_version="2.0"))
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    node = _node_by_step(result["compiled"], "c")
    assert node["type"] == "capability_call"
    assert node["config"]["capability"] == "catalog.products.search"
    assert node["config"]["contract_version"] == 1
    assert node["config"]["contract_hash"] == "hash-catalog.products.search-v1"
    assert node["config"]["idempotency"] == "best_effort"
    assert all(item["type"] != "marketplace_action" for item in result["compiled"]["graph"]["nodes"])
    _graph_ok(result["compiled"])


def test_multiple_branches_compile_then_and_else_ports() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Rama",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "d",
                "type": "decision",
                "goal": "¿Urgente?",
                "depends_on": ["t"],
                "params": {"field": "trigger.priority", "operator": "==", "value": "high"},
            },
            {
                "id": "y",
                "type": "notify",
                "goal": "Urgente",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {"channel": "in_app", "title": "Urgente", "message": "Sí"},
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Normal",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": False},
                "params": {"channel": "in_app", "title": "Normal", "message": "No"},
            },
        ],
    }
    _semantic, result = _compile(plan)
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    ports = {
        (edge["from_node"], edge["from_port"])
        for edge in result["compiled"]["graph"]["edges"]
    }
    d_id = _node_by_step(result["compiled"], "d")["id"]
    assert (d_id, "then") in ports
    assert (d_id, "else") in ports
    _graph_ok(result["compiled"])


def test_wait_compiles_correlation_timeout_and_payload_schema() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Esperar pago",
        "steps": [
            {"id": "t", "type": "trigger_conversation", "goal": "Mensaje"},
            {
                "id": "o",
                "type": "capability_call",
                "goal": "Obtener orden",
                "depends_on": ["t"],
                "params": {"capability": "orders.get", "inputs": {"order_id": "O-1"}},
            },
            {
                "id": "w",
                "type": "wait",
                "goal": "Esperar pago",
                "depends_on": ["o"],
                "params": {
                    "preset": "payment",
                    "event_type": "payment.succeeded",
                    "correlation": {"order_id": {"step": "o", "field": "order_id"}},
                    "timeout_seconds": 3600,
                    "on_timeout": "branch",
                    "expected_payload_schema": {
                        "type": "object",
                        "required": ["payment_reference"],
                        "properties": {"payment_reference": {"type": "string"}},
                    },
                },
            },
            {
                "id": "late",
                "type": "notify",
                "goal": "Pago vencido",
                "depends_on": ["w"],
                "when": {"step": "w", "outcome": False},
                "params": {"channel": "in_app", "title": "Vencido", "message": "Revisar"},
            },
            {
                "id": "confirm",
                "type": "capability_call",
                "goal": "Reservar inventario",
                "depends_on": ["w"],
                "when": {"step": "w", "outcome": True},
                "inputs": [{"step": "w", "field": "payment_reference", "to": "sku"}],
                "params": {"capability": "inventory.reserve", "inputs": {"quantity": 1}},
            },
            {
                "id": "end",
                "type": "stop",
                "goal": "Fin",
                "depends_on": ["confirm"],
                "params": {"status": "success"},
            },
        ],
    }
    _semantic, result = _compile(plan)
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    wait_node = _node_by_step(result["compiled"], "w")
    order_node = _node_by_step(result["compiled"], "o")
    assert wait_node["type"] == "wait_event"
    assert wait_node["config"]["correlation"] == {
        "order_id": f"{{{{nodes.{order_node['id']}.output.order_id}}}}"
    }
    assert wait_node["config"]["expected_payload_schema"]["required"] == [
        "payment_reference"
    ]
    assert wait_node["config"]["resume_mode"] == "durable_instance"
    assert {port["name"] for port in wait_node["output_ports"]} == {"out", "timeout"}
    _graph_ok(result["compiled"])


def test_loop_and_state_keep_target_limit_and_source_reference() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Agregar productos",
        "steps": [
            {"id": "t", "type": "trigger_conversation", "goal": "Cliente"},
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Buscar productos",
                "depends_on": ["t"],
                "params": {"capability": "catalog.products.search", "inputs": {"query": "arroz"}},
            },
            {
                "id": "s",
                "type": "state",
                "goal": "Guardar carrito",
                "depends_on": ["c"],
                "params": {
                    "op": "set",
                    "path": "cart.items",
                    "value_type": "array",
                    "source_reference": {"step": "c", "field": "products"},
                },
            },
            {
                "id": "d",
                "type": "decision",
                "goal": "¿Quiere otro?",
                "depends_on": ["s"],
                "params": {"field": "trigger.more", "operator": "==", "value": "yes"},
            },
            {
                "id": "l",
                "type": "loop",
                "goal": "¿Otro producto?",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {
                    "target": "c",
                    "max_iterations": 4,
                    "exit_condition": {"step": "d", "outcome": False},
                    "state_dependencies": ["cart.items"],
                },
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Cerrar",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": False},
                "params": {"channel": "in_app", "title": "Listo", "message": "Fin"},
            },
        ],
    }
    _semantic, result = _compile(plan)
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    loop_node = _node_by_step(result["compiled"], "l")
    state_node = _node_by_step(result["compiled"], "s")
    target = _node_by_step(result["compiled"], "c")
    assert loop_node["type"] == "loop"
    assert loop_node["config"]["max_iterations"] == 4
    assert loop_node["config"]["state_dependencies"] == ["cart.items"]
    assert state_node["config"]["value_type"] == "array"
    assert state_node["config"]["value"] == f"{{{{nodes.{target['id']}.output.products}}}}"
    assert any(
        edge["from_node"] == loop_node["id"]
        and edge["to_node"] == target["id"]
        and edge["from_port"] == "out"
        for edge in result["compiled"]["graph"]["edges"]
    )
    _graph_ok(result["compiled"])


def test_agent_and_human_approval_compile() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Evaluar y aprobar",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "a",
                "type": "agent_analysis",
                "goal": "Evaluar riesgo",
                "depends_on": ["t"],
                "params": {"agent_id": "a1", "prompt": "Evalúa el caso", "output_type": "text"},
            },
            {
                "id": "h",
                "type": "human_approval",
                "goal": "Aprobar",
                "depends_on": ["a"],
                "params": {"action": "Aprobar caso", "summary": "Revisar"},
            },
            {
                "id": "s",
                "type": "stop",
                "goal": "Fin",
                "depends_on": ["h"],
                "params": {"status": "success"},
            },
        ],
    }
    _semantic, result = _compile(plan)
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    nodes = result["compiled"]["graph"]["nodes"]
    assert any(node["type"] == "llm" for node in nodes)
    assert any(node["type"] == "human_approval" for node in nodes)
    _graph_ok(result["compiled"])


def test_financial_action_requires_approval() -> None:
    base = {
        "schema_version": "2.0",
        "goal": "Cobrar",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "p",
                "type": "capability_call",
                "goal": "Cobrar",
                "depends_on": ["t"],
                "params": {"capability": "payments.charge", "inputs": {"amount": 10}},
            },
            {"id": "s", "type": "stop", "goal": "Fin", "depends_on": ["p"], "params": {"status": "success"}},
        ],
    }
    semantic = normalize_semantic_plan(SemanticPlan.model_validate(base))
    issues = validate_semantic_plan(semantic, _caps(), permissions=_PERMS)
    assert any(issue.code == "approval.critical_action" for issue in issues)

    approved = {
        **base,
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {"id": "h", "type": "human_approval", "goal": "Aprobar cobro", "depends_on": ["t"]},
            {
                "id": "p",
                "type": "capability_call",
                "goal": "Cobrar",
                "depends_on": ["h"],
                "params": {"capability": "payments.charge", "inputs": {"amount": 10}},
            },
            {"id": "s", "type": "stop", "goal": "Fin", "depends_on": ["p"], "params": {"status": "success"}},
        ],
    }
    _semantic, result = _compile(approved)
    assert not [i for i in result["issues"] if i.code == "approval.critical_action"]
    _graph_ok(result["compiled"])


def test_compensation_creates_error_branch_and_failed_terminal() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Cobrar con compensación",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {"id": "h", "type": "human_approval", "goal": "Aprobar", "depends_on": ["t"]},
            {
                "id": "p",
                "type": "capability_call",
                "goal": "Cobrar",
                "depends_on": ["h"],
                "params": {"capability": "payments.charge", "inputs": {"amount": 10}},
            },
            {
                "id": "k",
                "type": "compensation",
                "goal": "Reembolsar",
                "depends_on": ["p"],
                "params": {
                    "target_step": "p",
                    "capability": "payments.refund",
                    "inputs": {"payment_id": "PAY-1"},
                },
            },
            {
                "id": "f",
                "type": "stop",
                "goal": "Falló el cobro",
                "depends_on": ["k"],
                "params": {"status": "failed", "message": "Cobro revertido"},
            },
            {
                "id": "ok",
                "type": "notify",
                "goal": "Cobro OK",
                "depends_on": ["p"],
                "params": {"channel": "in_app", "title": "OK", "message": "Cobrado"},
            },
        ],
    }
    _semantic, result = _compile(plan)
    assert not [i for i in result["issues"] if i.severity == "error"], result["issues"]
    target = _node_by_step(result["compiled"], "p")
    compensation = _node_by_step(result["compiled"], "k")
    assert target["error_policy"] == "branch"
    assert {port["name"] for port in target["output_ports"]} == {"out", "error"}
    assert compensation["type"] == "capability_call"
    assert compensation["config"]["compensation_for"] == target["id"]
    assert any(
        edge["from_node"] == target["id"]
        and edge["from_port"] == "error"
        and edge["to_node"] == compensation["id"]
        for edge in result["compiled"]["graph"]["edges"]
    )
    _graph_ok(result["compiled"])


def test_invalid_output_reference_and_type_mismatch_are_rejected() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Reservar stock",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Buscar productos",
                "depends_on": ["t"],
                "params": {"capability": "catalog.products.search", "inputs": {"query": "arroz"}},
            },
            {
                "id": "r",
                "type": "capability_call",
                "goal": "Reservar stock",
                "depends_on": ["c"],
                "inputs": [{"step": "c", "field": "products", "to": "sku"}],
                "params": {"capability": "inventory.reserve", "inputs": {"quantity": 1}},
            },
        ],
    }
    semantic = normalize_semantic_plan(SemanticPlan.model_validate(plan))
    issues = validate_semantic_plan(semantic, _caps(), permissions=_PERMS)
    codes = {issue.code for issue in issues}
    assert "contract.type_mismatch" in codes or "contract.input_unknown" in codes

    bad_field = {
        **plan,
        "steps": [
            plan["steps"][0],
            plan["steps"][1],
            {
                **plan["steps"][2],
                "inputs": [{"step": "c", "field": "missing_field", "to": "sku"}],
            },
        ],
    }
    issues = validate_semantic_plan(
        normalize_semantic_plan(SemanticPlan.model_validate(bad_field)),
        _caps(),
        permissions=_PERMS,
    )
    assert any(issue.code == "contract.output_unknown" for issue in issues)


def test_capability_contract_version_change_is_rejected() -> None:
    plan = _simple_plan(schema_version="2.0")
    plan["steps"][1]["contract_version"] = 2
    semantic = normalize_semantic_plan(SemanticPlan.model_validate(plan))
    issues = validate_semantic_plan(semantic, _caps(), permissions=_PERMS)
    assert any(issue.code == "contract.version_mismatch" for issue in issues)


def test_publish_gate_rejects_version_and_permission_change() -> None:
    from types import SimpleNamespace

    from src.platform.workflows.versions import _capability_publication_problems

    descriptor = SimpleNamespace(
        version=2,
        contract_hash="hash-v2",
        required_permissions=["external_actions:execute"],
        availability=SimpleNamespace(executable=True, status="AVAILABLE", reasons=[]),
    )
    problems = _capability_publication_problems(
        "payments.charge",
        {
            "contract_version": 1,
            "contract_hash": "hash-v1",
        },
        descriptor,
        frozenset({"workflows:create"}),
    )
    assert any("cambió de contrato" in item for item in problems)
    assert any("no puede ejecutar" in item for item in problems)


def test_loop_body_financial_action_declares_idempotency() -> None:
    plan = {
        "schema_version": "2.0",
        "goal": "Cobros repetidos",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {"id": "h", "type": "human_approval", "goal": "Aprobar", "depends_on": ["t"]},
            {
                "id": "p",
                "type": "capability_call",
                "goal": "Cobrar",
                "depends_on": ["h"],
                "idempotency": "none",
                "params": {"capability": "payments.charge", "inputs": {"amount": 10}},
            },
            {
                "id": "d",
                "type": "decision",
                "goal": "¿Reintentar?",
                "depends_on": ["p"],
                "params": {"field": "trigger.retry", "operator": "==", "value": "yes"},
            },
            {
                "id": "l",
                "type": "loop",
                "goal": "Reintentar cobro",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {"target": "p", "max_iterations": 2},
            },
            {
                "id": "z",
                "type": "stop",
                "goal": "Fin",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": False},
                "params": {"status": "success"},
            },
        ],
    }
    semantic = normalize_semantic_plan(SemanticPlan.model_validate(plan))
    issues = validate_semantic_plan(semantic, _caps(), permissions=_PERMS)
    codes = {issue.code for issue in issues}
    assert "loop.idempotency" in codes
    assert "contract.idempotency_required" in codes


async def test_wait_payload_schema_rejects_invalid_signal_before_claim() -> None:
    from src.platform.workflows.instances import _claim_and_resume

    result = await _claim_and_resume(
        {
            "organization_id": uuid4(),
            "waiting_for": {
                "expected_payload_schema": {
                    "type": "object",
                    "required": ["payment_reference"],
                    "properties": {"payment_reference": {"type": "string"}},
                }
            },
        },
        signal_row={"id": str(uuid4()), "payload": {}},
        port="out",
    )
    assert result["claimed"] is False
    assert result["status"] == "payload_invalid"
    assert result["errors"]


async def test_duplicate_signal_does_not_run_twice(async_client) -> None:
    from tests.test_workflow_durable_instances import (
        _durable_graph,
        _instance,
        _org,
        _signal,
        _start_instance,
        _workflow,
    )

    org = await _org(async_client, "Prompt04 Duplicate")
    workflow_id = await _workflow(async_client, org, "Dup", _durable_graph())
    started = await _start_instance(async_client, org, workflow_id)
    instance_id = started["instance"]["id"]
    first = await _signal(
        async_client,
        org,
        instance_id,
        event_type="conversation.message",
        payload={"text": "hola"},
        idempotency_key="p04-msg-1",
    )
    second = await _signal(
        async_client,
        org,
        instance_id,
        event_type="conversation.message",
        payload={"text": "hola"},
        idempotency_key="p04-msg-1",
    )
    assert first["status"] == "resumed"
    assert second["status"] == "duplicate"
    inst = await _instance(async_client, org, instance_id)
    assert inst["status"] == "COMPLETED"


def test_plan_step_limit_is_bounded_for_runtime() -> None:
    from src.platform.workflows.architect_models import MAX_SEMANTIC_STEPS

    steps = [{"id": "t", "type": "trigger_manual", "goal": "Inicio"}]
    steps.extend(
        {
            "id": f"n{index}",
            "type": "notify",
            "goal": f"Aviso {index}",
            "depends_on": ["t"],
            "params": {"channel": "in_app", "title": "x", "message": "y"},
        }
        for index in range(MAX_SEMANTIC_STEPS)
    )
    with pytest.raises(ValidationError):
        SemanticPlan.model_validate(
            {"schema_version": "2.0", "goal": "Grande", "steps": steps}
        )


def test_eighty_step_plan_compiles_within_contract_limit() -> None:
    from src.platform.workflows.architect_models import MAX_SEMANTIC_STEPS

    steps = [{"id": "t", "type": "trigger_manual", "goal": "Inicio"}]
    previous = "t"
    for index in range(MAX_SEMANTIC_STEPS - 1):
        step_id = f"n{index}"
        steps.append(
            {
                "id": step_id,
                "type": "notify",
                "goal": f"Aviso {index}",
                "depends_on": [previous],
                "params": {"channel": "in_app", "title": "x", "message": "y"},
            }
        )
        previous = step_id
    semantic = normalize_semantic_plan(
        SemanticPlan.model_validate(
            {"schema_version": "2.0", "goal": "Grande", "steps": steps}
        )
    )
    result = compile_semantic_plan(semantic, _caps())
    assert len(result["graph"]["nodes"]) == MAX_SEMANTIC_STEPS
    _graph_ok(result)


async def test_wait_resume_exposes_signal_payload_to_next_steps(async_client) -> None:
    from tests.test_workflow_durable_instances import (
        _instance,
        _org,
        _signal,
        _start_instance,
        _wait_node,
        _workflow,
    )
    from tests.test_workflow_graph import _edge, _graph, _node

    org = await _org(async_client, "Prompt04 Wait Payload")
    graph = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _wait_node("w", {"preset": "message"}),
            _node(
                "s",
                "state_set",
                {"path": "echo", "value": "{{nodes.w.output.text}}"},
            ),
            _node("end", "end"),
        ],
        edges=[
            _edge("e1", "t", "w"),
            _edge("e2", "w", "s"),
            _edge("e3", "s", "end"),
        ],
        entrypoints=["t"],
    )
    workflow_id = await _workflow(async_client, org, "Payload", graph)
    started = await _start_instance(async_client, org, workflow_id)
    signal = await _signal(
        async_client,
        org,
        started["instance"]["id"],
        event_type="conversation.message",
        payload={"text": "hola"},
    )
    assert signal["status"] == "resumed"
    inst = await _instance(async_client, org, started["instance"]["id"])
    assert inst["state"]["echo"] == "hola"


async def test_runtime_error_branch_runs_compensation_and_skips_success(
    monkeypatch,
) -> None:
    from src.platform.workflows import runtime
    from src.platform.workflows.runtime import ExecutionContext, execute_graph

    async def _no_persist(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None

    monkeypatch.setattr(runtime, "_persist_node_step", _no_persist)
    graph = WorkflowGraph.from_dict(
        {
            "workflow_version": 2,
            "nodes": [
                {"id": "t", "type": "trigger_webhook", "output_ports": [{"name": "out", "type": "json"}]},
                {
                    "id": "c",
                    "type": "capability_call",
                    "config": {"capability": ""},
                    "error_policy": "branch",
                    "input_ports": [{"name": "in", "type": "json"}],
                    "output_ports": [
                        {"name": "out", "type": "json"},
                        {"name": "error", "type": "json"},
                    ],
                },
                {
                    "id": "k",
                    "type": "stop",
                    "config": {"status": "failed", "message": "compensado"},
                    "input_ports": [{"name": "in", "type": "json"}],
                    "output_ports": [{"name": "out", "type": "json"}],
                },
                {
                    "id": "ok",
                    "type": "stop",
                    "config": {"status": "success"},
                    "input_ports": [{"name": "in", "type": "json"}],
                    "output_ports": [{"name": "out", "type": "json"}],
                },
            ],
            "edges": [
                {"id": "e1", "from_node": "t", "from_port": "out", "to_node": "c", "to_port": "in"},
                {"id": "e2", "from_node": "c", "from_port": "error", "to_node": "k", "to_port": "in"},
                {"id": "e3", "from_node": "c", "from_port": "out", "to_node": "ok", "to_port": "in"},
            ],
            "entrypoints": ["t"],
        }
    )
    result = await execute_graph(
        graph,
        ExecutionContext(
            organization_id=uuid4(),
            workflow_id=uuid4(),
            run_id=uuid4(),
            actor_type="user",
            trigger_type="manual",
            permissions=frozenset({"external_actions:execute"}),
        ),
        {},
    )
    assert result.status == "failed"
    assert result.node_executions["c"].status == "failed"
    assert result.node_executions["k"].status == "succeeded"
    assert result.node_executions["ok"].status == "skipped"


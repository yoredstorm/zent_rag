# =============================================================================
# Prompt 06 — Workflow Simulation, Validation y Self-Repair.
#
# La simulación usa execute_graph(simulate=True) sobre el mismo WorkflowGraph v2.
# No hay llamadas externas ni escrituras: los nodos externos se fijan con
# respuestas de escenario; los no cubiertos quedan UNVERIFIED.
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest

from src.platform.workflows.workflow_simulation import (
    ScenarioEvent,
    ScenarioResponse,
    SimulationScenario,
    simulate_semantic_plan,
)
from tests.test_workflow_semantic_v2 import _caps


def _plan(*, body: str = "linear") -> dict:
    steps = [
        {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
        {
            "id": "c",
            "type": "capability_call",
            "goal": "Buscar productos",
            "depends_on": ["t"],
            "params": {"capability": "catalog.products.search", "inputs": {"query": "arroz"}},
        },
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar",
            "depends_on": ["c"],
            "params": {"channel": "in_app", "title": "Productos", "message": "Listo"},
        },
    ]
    if body == "branch":
        steps = [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Consultar stock",
                "depends_on": ["t"],
                "params": {"capability": "inventory.stock.get", "inputs": {"sku": "A-1"}},
            },
            {
                "id": "d",
                "type": "decision",
                "goal": "¿Sin stock?",
                "depends_on": ["c"],
                "inputs": [{"step": "c", "field": "stock"}],
                "params": {"operator": "==", "value": 0},
            },
            {
                "id": "yes",
                "type": "notify",
                "goal": "Sin stock",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {"channel": "in_app", "title": "Sin stock", "message": "Reponer"},
            },
            {
                "id": "no",
                "type": "notify",
                "goal": "Con stock",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": False},
                "params": {"channel": "in_app", "title": "Stock", "message": "OK"},
            },
        ]
    elif body == "wait":
        steps = [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "w",
                "type": "wait",
                "goal": "Esperar al cliente",
                "depends_on": ["t"],
                "params": {"preset": "message", "on_timeout": "branch"},
            },
            {
                "id": "ok",
                "type": "notify",
                "goal": "Responder",
                "depends_on": ["w"],
                "when": {"step": "w", "outcome": True},
                "params": {"channel": "in_app", "title": "Respuesta", "message": "Recibida"},
            },
            {
                "id": "late",
                "type": "notify",
                "goal": "Timeout",
                "depends_on": ["w"],
                "when": {"step": "w", "outcome": False},
                "params": {"channel": "in_app", "title": "Timeout", "message": "Vencido"},
            },
        ]
    elif body == "loop":
        steps = [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Buscar",
                "depends_on": ["t"],
                "params": {"capability": "catalog.products.search", "inputs": {"query": "arroz"}},
            },
            {
                "id": "d",
                "type": "decision",
                "goal": "¿Otra?",
                "depends_on": ["c"],
                "params": {"field": "trigger.more", "operator": "==", "value": "yes"},
            },
            {
                "id": "l",
                "type": "loop",
                "goal": "Repetir",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {"target": "c", "max_iterations": 2},
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Fin",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": False},
                "params": {"channel": "in_app", "title": "Fin", "message": "Listo"},
            },
        ]
    elif body == "state":
        steps = [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "s",
                "type": "state",
                "goal": "Inicializar carrito",
                "depends_on": ["t"],
                "params": {"op": "set", "path": "cart.items", "value": [{"sku": "A-1"}]},
            },
            {
                "id": "a",
                "type": "state",
                "goal": "Agregar producto",
                "depends_on": ["s"],
                "params": {"op": "append", "path": "cart.items", "value": {"sku": "L-2"}},
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Listo",
                "depends_on": ["a"],
                "params": {"channel": "in_app", "title": "Carrito", "message": "OK"},
            },
        ]
    elif body == "approval":
        steps = [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "h",
                "type": "human_approval",
                "goal": "Aprobar",
                "depends_on": ["t"],
                "params": {"action": "Aprobar demo"},
            },
            {
                "id": "n",
                "type": "notify",
                "goal": "Aprobado",
                "depends_on": ["h"],
                "params": {"channel": "in_app", "title": "Aprobado", "message": "OK"},
            },
        ]
    return {"schema_version": "2.0", "goal": f"Escenario {body}", "steps": steps}


def _product_response(**output) -> ScenarioResponse:
    return ScenarioResponse(
        step_id="c",
        capability_ref="catalog.products.search",
        output={"products": [{"id": "P-1"}], **output},
    )


async def _simulate(plan: dict, scenario: SimulationScenario):
    return await simulate_semantic_plan(
        plan,
        _caps(),
        [scenario],
        organization_id=uuid4(),
        permissions=frozenset(
            {"workflows:read", "workflows:create", "external_actions:execute"}
        ),
    )


@pytest.mark.asyncio
async def test_linear_simulation_executes_real_deterministic_nodes() -> None:
    result = await _simulate(
        _plan(),
        SimulationScenario(
            scenario_id="linear",
            responses=[_product_response()],
        ),
    )
    assert result.state == "READY_TO_PUBLISH"
    report = result.scenarios[0]
    assert report.result == "PASSED"
    assert {item["type"] for item in report.executed_nodes} >= {
        "trigger_webhook",
        "capability_call",
        "notify",
    }
    assert report.trace["segments"] == 1


@pytest.mark.asyncio
async def test_branch_simulation_covers_taken_port_and_skips_other() -> None:
    result = await _simulate(
        _plan(body="branch"),
        SimulationScenario(
            scenario_id="branch",
            responses=[
                ScenarioResponse(
                    step_id="c",
                    capability_ref="inventory.stock.get",
                    output={"stock": 0},
                )
            ],
            expected_outputs={"yes": {"simulated": True, "channel": "in_app", "title": "Sin stock"}},
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    condition = next(
        item for item in report.executed_nodes if item["type"] == "condition"
    )
    assert condition["status"] in ("succeeded", "skipped")
    assert report.branch_coverage[condition["node_id"]]["taken"] == ["then"]


@pytest.mark.asyncio
async def test_wait_simulation_resumes_segment_with_event() -> None:
    result = await _simulate(
        _plan(body="wait"),
        SimulationScenario(
            scenario_id="wait",
            events=[
                ScenarioEvent(
                    event_type="conversation.message",
                    payload={"text": "quiero arroz"},
                )
            ],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    assert report.trace["segments"] == 2
    assert any(
        item["type"] == "notify" and item["status"] == "simulated"
        for item in report.executed_nodes
    )
    wait = next(item for item in report.executed_nodes if item["type"] == "wait_event")
    assert wait["output"]["signal_received"] is True


@pytest.mark.asyncio
async def test_wait_timeout_simulation_takes_timeout_branch() -> None:
    result = await _simulate(
        _plan(body="wait"),
        SimulationScenario(
            scenario_id="timeout",
            events=[
                ScenarioEvent(
                    event_type="workflow.wait.timeout",
                    payload={"reason": "deadline"},
                    port="timeout",
                )
            ],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    wait = next(item for item in report.executed_nodes if item["type"] == "wait_event")
    assert wait["output"]["port"] == "timeout"
    assert any(
        item["type"] == "notify"
        and item["status"] == "simulated"
        and item["output"].get("title") == "Timeout"
        for item in report.executed_nodes
    )


@pytest.mark.asyncio
async def test_loop_simulation_stops_at_bound() -> None:
    result = await _simulate(
        _plan(body="loop"),
        SimulationScenario(
            scenario_id="loop",
            initial_inputs={"more": "yes"},
            responses=[_product_response()],
            expected_result="FAILED",
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    assert report.failed_nodes
    assert any(item.get("loop") for item in report.timeline)


@pytest.mark.asyncio
async def test_state_simulation_reports_durable_transitions() -> None:
    result = await _simulate(
        _plan(body="state"),
        SimulationScenario(
            scenario_id="state",
            expected_state={
                "cart": {"items": [{"sku": "A-1"}, {"sku": "L-2"}]}
            },
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    assert report.state_transitions[-1]["state"]["cart"]["items"] == [
        {"sku": "A-1"},
        {"sku": "L-2"},
    ]


@pytest.mark.asyncio
async def test_approval_simulation_does_not_create_persistent_approval() -> None:
    result = await _simulate(
        _plan(body="approval"),
        SimulationScenario(
            scenario_id="approval",
            events=[ScenarioEvent(event_type="approval.decided", payload={"approved": True})],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    approval = next(
        item for item in report.executed_nodes if item["type"] == "human_approval"
    )
    assert approval["output"]["approval_id"].startswith("sim-approval-")


@pytest.mark.asyncio
async def test_duplicate_signal_is_ignored_without_second_effect() -> None:
    result = await _simulate(
        _plan(body="wait"),
        SimulationScenario(
            scenario_id="duplicate",
            events=[
                ScenarioEvent(
                    event_type="conversation.message",
                    payload={"text": "uno"},
                    idempotency_key="same-signal",
                ),
                ScenarioEvent(
                    event_type="conversation.message",
                    payload={"text": "uno"},
                    idempotency_key="same-signal",
                ),
            ],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    assert report.trace["events_consumed"] == 2
    assert any(item.get("duplicate_ignored") for item in report.timeline)
    assert (
        sum(
            1
            for item in report.executed_nodes
            if item["type"] == "notify"
            and item["status"] in ("simulated", "succeeded")
        )
        == 1
    )


@pytest.mark.asyncio
async def test_bounded_repair_applies_patch_to_draft_and_revalidates(monkeypatch) -> None:
    from src.platform.workflows.workflow_simulation import simulate_with_repair

    broken = _plan()
    broken["steps"][1]["params"]["capability"] = "does.not.exist"
    fixed = _plan()

    async def fake_patch(*args, **kwargs):  # noqa: ANN002, ANN003
        return {
            "plan": fixed,
            "patch": {"summary": "corregir referencia de capacidad"},
        }

    monkeypatch.setattr(
        "src.platform.workflows.architect.patch_workflow_plan", fake_patch
    )
    result = await simulate_with_repair(
        broken,
        _caps(),
        [SimulationScenario(scenario_id="repair", responses=[_product_response()])],
        organization_id=uuid4(),
        max_repairs=2,
    )
    assert result["changed"] is True
    assert result["attempts"][0]["accepted"] is True
    assert result["certification"]["scenarios"][0]["result"] == "PASSED"


@pytest.mark.asyncio
async def test_provider_failure_is_simulated_without_external_call() -> None:
    result = await _simulate(
        _plan(),
        SimulationScenario(
            scenario_id="provider-failure",
            responses=[
                ScenarioResponse(
                    step_id="c",
                    capability_ref="catalog.products.search",
                    error="PROVIDER_REJECTED",
                )
            ],
            expected_result="FAILED",
        ),
    )
    report = result.scenarios[0]
    assert report.result == "PASSED", report.model_dump()
    assert report.failed_nodes
    assert any(
        item["status"] == "failed" and item["simulated"]
        for item in report.failed_nodes
    )


@pytest.mark.asyncio
async def test_external_without_double_is_unverified_not_passed() -> None:
    result = await _simulate(
        _plan(),
        SimulationScenario(scenario_id="unverified"),
    )
    report = result.scenarios[0]
    assert report.result == "UNVERIFIED"
    assert report.unverified_nodes
    assert result.publishable is False


@pytest.mark.asyncio
async def test_forbidden_effect_fails_scenario() -> None:
    result = await _simulate(
        _plan(),
        SimulationScenario(
            scenario_id="forbidden",
            responses=[
                ScenarioResponse(
                    step_id="c",
                    capability_ref="catalog.products.search",
                    output={"products": []},
                    effects=["charge"],
                )
            ],
            forbidden_effects=["charge"],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "FAILED"
    assert report.unexpected_effects


@pytest.mark.asyncio
async def test_invalid_plan_is_blocked_before_simulation() -> None:
    plan = _plan()
    plan["steps"][1]["params"]["capability"] = "does.not.exist"
    result = await _simulate(
        plan,
        SimulationScenario(scenario_id="invalid"),
    )
    assert result.state == "FAILED_VALIDATION"
    assert result.publishable is False
    assert result.scenarios == []


@pytest.mark.asyncio
async def test_simulation_api_returns_certification_report(async_client) -> None:
    from tests.test_workflows import _create_org, _headers, _owner_session

    org = await _create_org(async_client, "Simulation API")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plan = {
        "schema_version": "2.0",
        "goal": "Avisar",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio"},
            {
                "id": "n",
                "type": "notify",
                "goal": "Avisar",
                "depends_on": ["t"],
                "params": {"channel": "in_app", "title": "Aviso", "message": "OK"},
            },
        ],
    }
    response = await async_client.post(
        "/api/v1/workflows/architect/simulate",
        headers=_headers(org),
        json={
            "plan": plan,
            "scenarios": [{"scenario_id": "api", "initial_inputs": {}}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_id"] == "zent.workflow.certification/v1"
    assert body["scenarios"][0]["result"] == "PASSED"
    assert body["publishable"] is True


@pytest.mark.asyncio
async def test_output_contract_mismatch_fails_scenario() -> None:
    result = await _simulate(
        _plan(),
        SimulationScenario(
            scenario_id="contract",
            responses=[
                ScenarioResponse(
                    step_id="c",
                    capability_ref="catalog.products.search",
                    output={},
                )
            ],
        ),
    )
    report = result.scenarios[0]
    assert report.result == "FAILED"
    assert report.output_contract_errors

# =============================================================================
# Workflow Architect — contrato canónico (Prompt 01).
#
# Verifica: estados del proceso creativo, envelope de observabilidad,
# multi-rama, clarificaciones, dependencias ausentes, fallback informado,
# guardado re-validado, gate de publicación, feature flag y compatibilidad
# legacy (headers de deprecación).
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.ir import WorkflowGraph, validate_graph
from tests.test_workflows import _create_org, _headers, _owner_session

SIMPLE_INTENT = {
    "goal": "Avisar cuando se cierre una venta",
    "trigger_intent": {"kind": "event", "event_type": "sales.closed"},
    "reasoning_needs": [],
    "confidence": 0.9,
}

SIMPLE_PLAN = {
    "goal": "Avisar cuando se cierre una venta",
    "steps": [
        {
            "id": "t",
            "type": "trigger_event",
            "goal": "Cuando se cierre una venta",
            "params": {"event_type": "sales.closed"},
        },
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar al equipo",
            "depends_on": ["t"],
            "params": {"channel": "in_app", "title": "Venta cerrada", "message": "Se cerró una venta"},
        },
    ],
}

BRANCH_PLAN = {
    "goal": "Avisar ventas grandes o pequeñas",
    "steps": [
        {
            "id": "t",
            "type": "trigger_event",
            "goal": "Cuando se cierre una venta",
            "params": {"event_type": "sales.closed"},
        },
        {
            "id": "d",
            "type": "decision",
            "goal": "¿Es una venta grande?",
            "depends_on": ["t"],
            "params": {"field": "trigger.amount", "operator": ">", "value": 20000},
        },
        {
            "id": "big",
            "type": "notify",
            "goal": "Avisar al gerente",
            "depends_on": ["d"],
            "when": {"step": "d", "outcome": True},
            "params": {"channel": "in_app", "title": "Venta grande", "message": "Revisar"},
        },
        {
            "id": "small",
            "type": "notify",
            "goal": "Avisar al equipo",
            "depends_on": ["d"],
            "when": {"step": "d", "outcome": False},
            "params": {"channel": "in_app", "title": "Venta", "message": "Registrada"},
        },
    ],
}

CLARIFY_PLAN = {
    "goal": "Avisar al responsable",
    "steps": [
        {
            "id": "t",
            "type": "trigger_manual",
            "goal": "Inicio manual",
        },
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar al responsable",
            "depends_on": ["t"],
            "params": {"channel": "in_app", "title": "Aviso", "message": "Hola"},
        },
    ],
    "assumptions": [
        {
            "statement": "El responsable es el gerente comercial",
            "impact": "high",
            "needs_confirmation": True,
        }
    ],
}

MISSING_INTEGRATION_PLAN = {
    "goal": "Consultar una integración ausente",
    "steps": [
        {"id": "t", "type": "trigger_manual", "goal": "Inicio manual"},
        {
            "id": "i",
            "type": "integration_action",
            "goal": "Consultar demo",
            "depends_on": ["t"],
            "params": {"action_id": "demo.echo", "inputs": {"text": "hola"}},
        },
    ],
}

WAIT_PLAN = {
    "goal": "Esperar pago y avisar si vence",
    "steps": [
        {
            "id": "t",
            "type": "trigger_event",
            "goal": "Pago pendiente",
            "params": {"event_type": "payment.pending"},
        },
        {
            "id": "w",
            "type": "wait",
            "goal": "Esperar el pago",
            "depends_on": ["t"],
            "params": {"preset": "payment", "timeout_seconds": 3600, "on_timeout": "branch"},
        },
        {
            "id": "late",
            "type": "notify",
            "goal": "Avisar pago vencido",
            "depends_on": ["w"],
            "when": {"step": "w", "outcome": False},
            "params": {"channel": "in_app", "title": "Pago vencido", "message": "Revisar"},
        },
    ],
}


class _ScriptedProvider:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        index = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        payload = self.payloads[index]
        return SimpleNamespace(content=json.dumps(payload))


class _InvalidProvider:
    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        return SimpleNamespace(content="esto no es json")


def _override(provider: object):
    from src.api.deps import get_llm_provider
    from src.api.main import app

    app.dependency_overrides[get_llm_provider] = lambda: provider

    def restore() -> None:
        app.dependency_overrides.pop(get_llm_provider, None)

    return restore


async def _plan(
    async_client: AsyncClient,
    org: dict,
    provider: object,
    *,
    prompt: str = "Cuando se cierre una venta avisa al equipo",
    **extra,
):
    restore = _override(provider)
    try:
        response = await async_client.post(
            "/api/v1/workflows/architect/plan",
            headers={**_headers(org), "Idempotency-Key": f"can-{uuid4().hex}"},
            json={"prompt": prompt, **extra},
        )
    finally:
        restore()
    return response


@pytest.mark.asyncio
async def test_plan_returns_canonical_envelope_and_valid_graph(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Envelope")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, SIMPLE_PLAN])
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["state"] == "DRAFT_READY"
    assert body["publishable"] is True
    assert body["session_id"].startswith("ds_")
    assert body["planner"]["version"].startswith("architect/")
    assert body["planner"]["source"] == "llm"
    assert body["plan_hash"] and len(body["plan_hash"]) == 64
    assert [phase["name"] for phase in body["phases"]] == [
        "discovery",
        "intent",
        "planning",
        "validation",
        "compilation",
        "readiness",
    ]
    assert body["fallback"] is None
    assert body["blockers"] == []
    assert body["graph"] is not None
    validate_graph(WorkflowGraph.from_dict(body["graph"]))
    node_types = {node["type"] for node in body["graph"]["nodes"]}
    assert {"trigger_event", "notify"} <= node_types


@pytest.mark.asyncio
async def test_plan_compiles_both_decision_branches(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Branch")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, BRANCH_PLAN])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    graph = body["graph"]
    assert graph is not None
    validate_graph(WorkflowGraph.from_dict(graph))
    condition = next(node for node in graph["nodes"] if node["type"] == "condition")
    ports = {
        edge["from_port"] for edge in graph["edges"] if edge["from_node"] == condition["id"]
    }
    assert ports == {"then", "else"}
    notify_nodes = [node for node in graph["nodes"] if node["type"] == "notify"]
    assert len(notify_nodes) == 2


@pytest.mark.asyncio
async def test_plan_with_high_impact_assumption_needs_clarification(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Canonical Clarify")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, CLARIFY_PLAN])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "NEEDS_CLARIFICATION"
    assert body["publishable"] is False
    assert any(item["code"] == "assumption.high_impact" for item in body["clarifications"])
    assert body["graph"] is not None  # se puede revisar, no publicar


@pytest.mark.asyncio
async def test_missing_integration_needs_configuration_and_no_graph(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Canonical Missing")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client,
        org,
        _ScriptedProvider([SIMPLE_INTENT, MISSING_INTEGRATION_PLAN]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "NEEDS_CONFIGURATION"
    assert body["graph"] is None
    assert body["publishable"] is False
    assert "integration:demo.echo" in {
        item["requirement"] for item in body["requirements"]
    }
    assert any(item["kind"] == "requirement" for item in body["blockers"])


@pytest.mark.asyncio
async def test_invalid_llm_response_returns_informed_fallback(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Fallback")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    prompt = "Cuando el stock sea menor a 5 avisa a compras y registra el resultado"
    response = await _plan(async_client, org, _InvalidProvider(), prompt=prompt)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "heuristics"
    assert body["fallback"]["used"] is True
    assert body["fallback"]["reason_code"] == "invalid_llm_response"
    assert body["fallback"]["preserved_requirement"] == prompt
    assert body["fallback"]["limitations"]
    assert body["publishable"] is False
    assert body["state"] in {"NEEDS_CLARIFICATION", "NEEDS_CONFIGURATION", "BLOCKED"}
    assert body["state"] != "DRAFT_READY"


@pytest.mark.asyncio
async def test_wait_timeout_branch_uses_timeout_port(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Wait")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, WAIT_PLAN])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    graph = body["graph"]
    assert graph is not None, body["issues"]
    validate_graph(WorkflowGraph.from_dict(graph))
    wait_node = next(node for node in graph["nodes"] if node["type"] == "wait_event")
    assert {port["name"] for port in wait_node["output_ports"]} == {"out", "timeout"}
    assert any(
        edge["from_node"] == wait_node["id"] and edge["from_port"] == "timeout"
        for edge in graph["edges"]
    )
    assert body["state"] == "DRAFT_READY"


@pytest.mark.asyncio
async def test_draft_endpoint_revalidates_and_saves_only_draft(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Draft")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    planned = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, SIMPLE_PLAN])
    )
    body = planned.json()

    saved = await async_client.post(
        "/api/v1/workflows/architect/draft",
        headers={**_headers(org), "Idempotency-Key": f"draft-{uuid4().hex}"},
        json={
            "plan": body["plan"],
            "plan_hash": body["plan_hash"],
            "session_id": body["session_id"],
            "name": "Aviso de venta cerrada",
            "source": "llm",
        },
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()
    assert draft["state"] == "DRAFT_READY"
    assert draft["session_id"] == body["session_id"]
    assert draft["workflow_id"]

    detail = await async_client.get(
        f"/api/v1/workflows/{draft['workflow_id']}", headers=_headers(org)
    )
    assert detail.status_code == 200, detail.text
    workflow = detail.json()
    assert workflow["status"] == "draft"  # nunca se activa por "alta confianza"
    metadata = workflow["graph"]["metadata"]
    assert metadata["architect"] is True
    assert metadata["architect_state"] == "DRAFT_READY"
    assert metadata["architect_session_id"] == body["session_id"]


@pytest.mark.asyncio
async def test_draft_endpoint_rejects_plan_with_unresolved_dependency(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Canonical Draft Blocked")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await _plan(
        async_client,
        org,
        _ScriptedProvider([SIMPLE_INTENT, MISSING_INTEGRATION_PLAN]),
    )
    body = response.json()
    saved = await async_client.post(
        "/api/v1/workflows/architect/draft",
        headers={**_headers(org), "Idempotency-Key": f"draftb-{uuid4().hex}"},
        json={"plan": body["plan"], "name": "No debe guardarse"},
    )
    assert saved.status_code == 422, saved.text
    payload = saved.json()
    assert payload["saved"] is False
    assert payload["state"] == "NEEDS_CONFIGURATION"
    assert "workflow_id" not in payload


@pytest.mark.asyncio
async def test_patch_rejects_stale_plan_hash(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Patch Hash")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    planned = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, SIMPLE_PLAN])
    )
    body = planned.json()
    response = await async_client.post(
        "/api/v1/workflows/architect/patch",
        headers={**_headers(org), "Idempotency-Key": f"patchh-{uuid4().hex}"},
        json={
            "plan": {**body["plan"], "goal": "Otro objetivo distinto"},
            "instruction": "quita la aprobación",
            "plan_hash": body["plan_hash"],
            "session_id": body["session_id"],
        },
    )
    assert response.status_code == 409, response.text


@pytest.mark.asyncio
async def test_publish_blocks_unreviewed_fallback_draft(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Publish Fallback")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    planned = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, SIMPLE_PLAN])
    )
    body = planned.json()
    saved = await async_client.post(
        "/api/v1/workflows/architect/draft",
        headers={**_headers(org), "Idempotency-Key": f"draftf-{uuid4().hex}"},
        json={
            "plan": body["plan"],
            "plan_hash": body["plan_hash"],
            "session_id": body["session_id"],
            "name": "Borrador por reglas",
            "source": "heuristics",
        },
    )
    assert saved.status_code == 200, saved.text
    workflow_id = saved.json()["workflow_id"]

    response = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pubf-{uuid4().hex}"},
        json={"notes": "intento sin revisar"},
    )
    assert response.status_code == 400, response.text
    assert "confirma" in response.text.lower()

    detail = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=_headers(org)
    )
    assert detail.json()["status"] == "draft"

    confirmed = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pubfc-{uuid4().hex}"},
        json={"notes": "revisado por una persona", "confirm_architect_draft": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"


@pytest.mark.asyncio
async def test_publish_ready_architect_workflow_activates(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Publish Ready")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    planned = await _plan(
        async_client, org, _ScriptedProvider([SIMPLE_INTENT, SIMPLE_PLAN])
    )
    body = planned.json()
    saved = await async_client.post(
        "/api/v1/workflows/architect/draft",
        headers={**_headers(org), "Idempotency-Key": f"draftr-{uuid4().hex}"},
        json={"plan": body["plan"], "plan_hash": body["plan_hash"], "name": "Aviso listo"},
    )
    workflow_id = saved.json()["workflow_id"]
    response = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/publish",
        headers={**_headers(org), "Idempotency-Key": f"pubr-{uuid4().hex}"},
        json={"notes": "publicar"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"


@pytest.mark.asyncio
async def test_architect_feature_flag_is_reversible(
    async_client: AsyncClient, monkeypatch
) -> None:
    org = await _create_org(async_client, "Canonical Flag")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    response = await async_client.get(
        "/api/v1/workflows/architect/config", headers=_headers(org)
    )
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True
    assert "DRAFT_READY" in response.json()["states"]

    monkeypatch.setenv("RAG_WORKFLOW_ARCHITECT_ENABLED", "false")
    disabled = await async_client.get(
        "/api/v1/workflows/architect/config", headers=_headers(org)
    )
    assert disabled.json()["enabled"] is False


@pytest.mark.asyncio
async def test_plan_uses_preferred_agent_for_ai_steps(async_client: AsyncClient) -> None:
    from src.platform.workflows.architect import plan_workflow

    capabilities = {
        "available": {
            "agents": True,
            "knowledge_bases": False,
            "installed_integrations": False,
            "managed_db": False,
        },
        "agents": [
            {"id": "ag1", "name": "Analista", "purpose": "Analiza ventas y riesgo", "tools": []}
        ],
        "knowledge_bases": [],
        "actions": [],
        "events": ["sales.closed"],
        "managed_db": False,
        "permissions": ["agents:execute"],
    }
    plan = {
        "goal": "Analizar el riesgo de la venta",
        "steps": [
            {
                "id": "t",
                "type": "trigger_event",
                "goal": "Venta cerrada",
                "params": {"event_type": "sales.closed"},
            },
            {
                "id": "a",
                "type": "agent_analysis",
                "goal": "Analizar el riesgo",
                "depends_on": ["t"],
                "params": {"prompt": "Analiza el riesgo de esta venta"},
            },
        ],
    }
    result = await plan_workflow(
        uuid4(),
        "Analiza el riesgo de cada venta cerrada",
        capabilities=capabilities,
        provider=_ScriptedProvider([SIMPLE_INTENT, plan]),
        permissions=frozenset({"agents:execute"}),
        preferred_agent_id="ag1",
    )
    assert result["graph"] is not None, result["issues"]
    llm = next(node for node in result["graph"]["nodes"] if node["type"] == "llm")
    assert llm["config"]["agent_id"] == "ag1"


@pytest.mark.asyncio
async def test_legacy_copilot_is_marked_deprecated(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Canonical Legacy")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    restore = _override(
        _ScriptedProvider(
            [
                {
                    "name": "Aviso simple",
                    "trigger": {"kind": "manual"},
                    "actions": [{"kind": "notify", "channel": "zent", "message": "hola"}],
                }
            ]
        )
    )
    try:
        response = await async_client.post(
            "/api/v1/workflows/copilot/intent",
            headers={**_headers(org), "Idempotency-Key": f"legacy-{uuid4().hex}"},
            json={"prompt": "avísame algo cuando pase algo"},
        )
    finally:
        restore()
    assert response.status_code == 200, response.text
    assert response.headers["Deprecation"] == "true"
    assert "architect/plan" in response.headers["Link"]
    assert response.headers["Sunset"]

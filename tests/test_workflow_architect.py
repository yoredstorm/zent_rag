# =============================================================================
# Workflow Architect — First delivery: discovery, intent, plan, compiler,
# validator + dataset de intents (A–M, brief §29/§34).
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.workflows.architect_compiler import compile_semantic_plan
from src.platform.workflows.architect_models import SemanticPlan
from src.platform.workflows.architect_validator import validate_semantic_plan
from tests.test_workflows import _create_org, _headers, _owner_session


def _caps(
    *,
    agents: list[dict] | None = None,
    kbs: tuple[str, ...] = ("kb1",),
    actions: list[dict] | None = None,
    managed: bool = True,
    permissions: frozenset[str] | None = None,
) -> dict:
    return {
        "available": {
            "agents": bool(agents),
            "knowledge_bases": bool(kbs),
            "installed_integrations": bool(actions),
            "managed_db": managed,
        },
        "agents": agents or [],
        "knowledge_bases": list(kbs),
        "actions": actions or [],
        "events": ["sales.closed", "document.processed"],
        "permissions": sorted(permissions) if permissions is not None else None,
    }


def _sale_plan() -> SemanticPlan:
    return SemanticPlan.model_validate(
        {
            "goal": "Revisar ventas grandes y pedir aprobación si corresponde",
            "steps": [
                {"id": "t", "type": "trigger_event", "goal": "Cuando se cierre una venta",
                 "params": {"event_type": "sales.closed"}},
                {"id": "q", "type": "business_query", "goal": "Historial del cliente",
                 "depends_on": ["t"], "params": {"ask": "historial del cliente"}},
                {"id": "k", "type": "knowledge_query", "goal": "Política comercial",
                 "depends_on": ["t"], "params": {"operation": "answer", "query": "política comercial"}},
                {"id": "a", "type": "agent_analysis", "goal": "Determinar si la venta requiere revisión",
                 "depends_on": ["q", "k"],
                 "inputs": [
                     {"step": "q", "field": "rows", "label": "Historial"},
                     {"step": "k", "field": "citations", "label": "Política"},
                 ],
                 "params": {"prompt": "Analiza ventas y política", "output_type": "business_assessment"}},
                {"id": "d", "type": "decision", "goal": "¿Requiere revisión?",
                 "depends_on": ["a"], "inputs": [{"step": "a", "field": "requires_review"}]},
                {"id": "ap", "type": "human_approval", "goal": "Pedir aprobación del gerente",
                 "depends_on": ["d"], "when": {"step": "d", "outcome": True},
                 "params": {"action": "Aprobar venta de alto monto"}},
                {"id": "n", "type": "notify", "goal": "Avisar a Ventas",
                 "depends_on": ["ap"], "params": {"channel": "in_app"}},
            ],
        }
    )


def _stock_plan(with_agent: bool) -> SemanticPlan:
    steps = [
        {"id": "t", "type": "trigger_event", "goal": "Cambio de inventario",
         "params": {"event_type": "inventory.stock.low"}},
        {"id": "d", "type": "decision", "goal": "¿Stock bajo?",
         "depends_on": ["t"], "params": {"field": "trigger.stock", "operator": "<", "value": 10}},
        {"id": "n", "type": "notify", "goal": "Avisar a Compras",
         "depends_on": ["d"], "when": {"step": "d", "outcome": True},
         "params": {"channel": "in_app"}},
    ]
    if with_agent:
        steps.append(
            {
                "id": "a",
                "type": "agent_analysis",
                "goal": "Analizar ventas, política y tiempo del proveedor para recomendar cuánto comprar",
                "depends_on": ["d"],
                "when": {"step": "d", "outcome": True},
                "params": {"prompt": "Recomienda cuánto comprar"},
            }
        )
    return SemanticPlan.model_validate({"goal": "Reponer stock", "steps": steps})


def _node_by_step(graph: dict, steps_map: dict[str, str], step_id: str) -> dict:
    node_id = steps_map[step_id]
    return next(node for node in graph["nodes"] if node["id"] == node_id)


def _issue_codes(issues: list) -> set[str]:
    return {issue.code for issue in issues}


def test_compiler_maps_sale_plan_with_semantic_refs() -> None:
    caps = _caps(agents=[{"id": "a1", "name": "Analista de Ventas", "purpose": "Analiza ventas"}])
    result = compile_semantic_plan(_sale_plan(), caps)
    graph = result["graph"]
    types = {node["type"] for node in graph["nodes"]}
    assert {"trigger_event", "query_business_data", "kb_query", "llm", "condition", "human_approval", "notify"} <= types

    llm = _node_by_step(graph, result["steps_map"], "a")
    assert llm["config"]["agent_id"] == "a1"
    assert llm["config"]["context_mode"] == "manual"
    selectors = llm["config"]["context_selectors"]
    assert f"data:{result['steps_map']['q']}" in selectors
    assert f"knowledge:{result['steps_map']['k']}" in selectors
    assert "evidence" in selectors

    condition = _node_by_step(graph, result["steps_map"], "d")
    assert condition["config"]["field"] == f"{{{{nodes.{result['steps_map']['a']}.output.requires_review}}}}"

    approval_edge = next(
        edge for edge in graph["edges"] if edge["to_node"] == result["steps_map"]["ap"]
    )
    assert approval_edge["from_port"] == "then"
    assert approval_edge["from_node"] == result["steps_map"]["d"]


def test_validation_sale_plan_is_ready() -> None:
    caps = _caps(agents=[{"id": "a1", "name": "Analista de Ventas", "purpose": "Analiza ventas"}])
    issues = validate_semantic_plan(_sale_plan(), caps)
    assert not [issue for issue in issues if issue.severity == "error"], issues


def test_stock_threshold_plan_avoids_agent() -> None:
    caps = _caps(agents=[])
    plan = _stock_plan(with_agent=False)
    issues = validate_semantic_plan(plan, caps)
    assert "missing.agents" not in _issue_codes(issues)
    result = compile_semantic_plan(plan, caps)
    types = {node["type"] for node in result["graph"]["nodes"]}
    assert "llm" not in types


def test_analysis_justified_plan_uses_matching_agent() -> None:
    caps = _caps(
        agents=[
            {"id": "legal-1", "name": "Área Legal", "purpose": "Revisa contratos y cláusulas legales"},
            {"id": "sales-1", "name": "Analista de Ventas", "purpose": "Analiza ventas, stock y proveedores"},
        ]
    )
    plan = _stock_plan(with_agent=True)
    issues = validate_semantic_plan(plan, caps)
    assert "missing.agents" not in _issue_codes(issues)
    result = compile_semantic_plan(plan, caps)
    llm = _node_by_step(result["graph"], result["steps_map"], "a")
    assert llm["config"]["agent_id"] == "sales-1"


def test_missing_integration_reports_requirement() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Consultar Pokémon",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "i", "type": "integration_action", "goal": "Consultar Pikachu",
                 "depends_on": ["t"],
                 "params": {"action_id": "demo.pokemon.lookup", "inputs": {"name": "pikachu"}}},
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    errors = [issue for issue in issues if issue.severity == "error"]
    assert errors and errors[0].code == "missing.integration"
    assert "conectar" in errors[0].message
    assert errors[0].requirement == "integration:demo.pokemon.lookup"


def test_slack_notify_requires_connection() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Avisar por Slack",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "n", "type": "notify", "goal": "Avisar a Compras",
                 "depends_on": ["t"], "params": {"channel": "slack"}},
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    errors = [issue for issue in issues if issue.severity == "error"]
    assert errors[0].requirement == "integration:slack"
    assert "Slack" in errors[0].message


def test_cycle_is_rejected() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Ciclo",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "a", "type": "notify", "goal": "A", "depends_on": ["b"]},
                {"id": "b", "type": "notify", "goal": "B", "depends_on": ["a"]},
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    assert "plan.cycle" in _issue_codes(issues)


def test_orphan_step_gets_implicit_trigger_warning() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Huérfano",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "n", "type": "notify", "goal": "Avisar", "params": {"channel": "in_app"}},
            ],
        }
    )
    result = compile_semantic_plan(plan, _caps())
    assert "compile.implicit_trigger" in _issue_codes(result["issues"])
    assert any(
        edge["from_node"] == result["steps_map"]["t"]
        and edge["to_node"] == result["steps_map"]["n"]
        for edge in result["graph"]["edges"]
    )


def test_high_impact_assumption_asks_confirmation() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Aprobación de pago",
            "steps": [{"id": "t", "type": "trigger_manual", "goal": "Manual"}],
            "assumptions": [
                {"statement": "Notificaremos a finanzas@acme.com", "impact": "high"}
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    assert "assumption.high_impact" in _issue_codes(issues)


def test_decision_without_input_is_error() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Decisión",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "d", "type": "decision", "goal": "¿Sí o no?", "depends_on": ["t"]},
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    assert "missing.decision_input" in _issue_codes(issues)


def test_unknown_knowledge_operation_is_error() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "Conocimiento",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "Manual"},
                {"id": "k", "type": "knowledge_query", "goal": "Buscar",
                 "depends_on": ["t"], "params": {"operation": "teleport", "query": "x"}},
            ],
        }
    )
    issues = validate_semantic_plan(plan, _caps())
    assert "plan.knowledge_operation" in _issue_codes(issues)


# ---------------------------------------------------------------------------
# Endpoint: pipeline completo con provider fake
# ---------------------------------------------------------------------------
class _FakeProvider:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        if not self._responses:
            raise RuntimeError("sin respuestas")
        return SimpleNamespace(content=json.dumps(self._responses.pop(0)), model="fake")


class _BoomProvider:
    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        raise RuntimeError("llm caído")


_SALE_INTENT = {
    "goal": "Revisar ventas grandes y pedir aprobación",
    "trigger_intent": {"kind": "event", "event_type": "sales.closed"},
    "data_needs": ["historial del cliente"],
    "knowledge_needs": ["política comercial"],
    "reasoning_needs": ["evaluar si requiere revisión"],
    "approval_needs": ["gerente"],
    "actions": ["notificar a ventas"],
    "confidence": 0.8,
}

_SALE_PLAN = {
    "goal": "Revisar ventas grandes y pedir aprobación",
    "steps": [
        {"id": "t", "type": "trigger_event", "goal": "Cuando se cierre una venta",
         "params": {"event_type": "sales.closed"}},
        {"id": "q", "type": "business_query", "goal": "Historial del cliente",
         "depends_on": ["t"], "params": {"ask": "historial del cliente"}},
        {"id": "k", "type": "knowledge_query", "goal": "Política comercial",
         "depends_on": ["t"], "params": {"operation": "answer", "query": "política comercial"}},
        {"id": "a", "type": "agent_analysis", "goal": "Determinar si la venta requiere revisión",
         "depends_on": ["q", "k"],
         "inputs": [{"step": "q", "field": "rows"}, {"step": "k", "field": "citations"}],
         "params": {"prompt": "Analiza ventas y política", "output_type": "business_assessment"}},
        {"id": "d", "type": "decision", "goal": "¿Requiere revisión?",
         "depends_on": ["a"], "inputs": [{"step": "a", "field": "requires_review"}]},
        {"id": "ap", "type": "human_approval", "goal": "Pedir aprobación",
         "depends_on": ["d"], "when": {"step": "d", "outcome": True},
         "params": {"action": "Aprobar venta"}},
        {"id": "n", "type": "notify", "goal": "Avisar a Ventas",
         "depends_on": ["ap"], "params": {"channel": "in_app"}},
    ],
}


async def _setup_capabilities(async_client: AsyncClient, org: dict) -> None:
    org["session"] = await _owner_session(async_client, org["organization_id"])
    kb = await async_client.post(
        "/api/v1/knowledge-bases", json={"name": f"kb-{uuid4().hex[:6]}"}, headers=_headers(org)
    )
    assert kb.status_code == 201, kb.text
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={"name": "Analista de Ventas", "system_prompt": "responde corto", "tools": []},
    )
    assert agent.status_code == 201, agent.text

    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.workspaces.service import ensure_default_workspace

    organization_id = UUID(org["organization_id"])
    workspace = await ensure_default_workspace(
        PostgresWorkspaceRepository(), organization_id
    )
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO managed_databases (id, organization_id, workspace_id, db_name) "
                "VALUES (gen_random_uuid(), :oid, :ws, :db)"
            ),
            {"oid": org["organization_id"], "ws": str(workspace.id), "db": f"arch_{uuid4().hex[:8]}"},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_architect_endpoint_plans_and_compiles(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Architect E2E")
    await _setup_capabilities(async_client, org)

    app.dependency_overrides[get_llm_provider] = lambda: _FakeProvider(
        [dict(_SALE_INTENT), dict(_SALE_PLAN)]
    )
    try:
        resp = await async_client.post(
            "/api/v1/workflows/architect/plan",
            headers={**_headers(org), "Idempotency-Key": f"ar-{uuid4().hex}"},
            json={"prompt": "Cuando una venta supere S/40000, revisa la política y pide aprobación si corresponde."},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "llm"
    assert body["graph"] is not None
    assert body["issues"] is not None
    assert not [issue for issue in body["issues"] if issue["severity"] == "error"], body["issues"]
    kinds = {item["kind"] for item in body["preview"]}
    assert {"when", "get", "consult", "analyze", "if", "then", "after"} <= kinds
    node_types = {node["type"] for node in body["graph"]["nodes"]}
    assert {"query_business_data", "kb_query", "llm", "condition", "human_approval"} <= node_types
    assert body["cost"] is not None


@pytest.mark.asyncio
async def test_architect_endpoint_reports_missing_capabilities(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Architect Missing")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    app.dependency_overrides[get_llm_provider] = lambda: _FakeProvider(
        [dict(_SALE_INTENT), dict(_SALE_PLAN)]
    )
    try:
        resp = await async_client.post(
            "/api/v1/workflows/architect/plan",
            headers={**_headers(org), "Idempotency-Key": f"arm-{uuid4().hex}"},
            json={"prompt": "Cuando una venta supere S/40000, revisa la política y pide aprobación."},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["graph"] is None
    codes = {issue["code"] for issue in body["issues"]}
    assert "missing.managed_db" in codes
    assert "missing.agents" in codes


@pytest.mark.asyncio
async def test_architect_fallback_without_llm(async_client: AsyncClient) -> None:
    from src.api.deps import get_llm_provider
    from src.api.main import app

    org = await _create_org(async_client, "Architect Fallback")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    app.dependency_overrides[get_llm_provider] = lambda: _BoomProvider()
    try:
        resp = await async_client.post(
            "/api/v1/workflows/architect/plan",
            headers={**_headers(org), "Idempotency-Key": f"arf-{uuid4().hex}"},
            json={"prompt": "Todos los días a las 8 analiza ventas y dime qué cambió contra ayer."},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "heuristics"
    assert body["notes"]
    assert body["plan"]["steps"]

# =============================================================================
# Prompt 02 — el planner puede usar capacidades de negocio (capability_call)
# y no guarda con un snapshot de catálogo obsoleto.
# =============================================================================
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.marketplace.runtime import install_integration
from src.platform.workflows.architect import plan_workflow
from src.platform.workflows.architect_models import SemanticPlan
from src.platform.workflows.capability_registry import refs_for_plan
from tests.test_workflows import _create_org, _headers, _owner_session

_PERMS = frozenset(
    {"workflows:read", "workflows:create", "external_actions:execute", "agents:execute"}
)

_INTENT = {
    "goal": "Buscar productos y avisar",
    "trigger_intent": {"kind": "manual"},
    "reasoning_needs": [],
    "confidence": 0.9,
}

_PLAN = {
    "goal": "Buscar productos y avisar",
    "steps": [
        {"id": "t", "type": "trigger_manual", "goal": "Inicio manual"},
        {
            "id": "c",
            "type": "capability_call",
            "goal": "Buscar productos del catálogo",
            "depends_on": ["t"],
            "params": {"capability": "catalog.products.search", "inputs": {"query": "arroz"}},
        },
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar",
            "depends_on": ["c"],
            "params": {"channel": "in_app", "title": "Productos", "message": "Encontrados"},
        },
    ],
}


def _caps(executable: bool = True) -> dict:
    return {
        "available": {
            "agents": False,
            "knowledge_bases": False,
            "installed_integrations": True,
            "managed_db": False,
        },
        "agents": [],
        "knowledge_bases": [],
        "actions": {},
        "managed_db": False,
        "events": [],
        "permissions": sorted(_PERMS),
        "capability_index": {
            "catalog.products.search": {
                "capability_ref": "catalog.products.search",
                "version": 1,
                "display_name": "Buscar productos",
                "required_inputs": ["query"],
                "input_schema": {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string"}},
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"products": {"type": "array"}},
                },
                "required_permissions": ["external_actions:execute"],
                "availability": {
                    "status": "AVAILABLE" if executable else "NEEDS_CONFIGURATION",
                    "executable": executable,
                    "reasons": [] if executable else ["sin binding para este tenant"],
                },
            }
        },
    }


class _Provider:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def generate(self, prompt, **kwargs):  # noqa: ANN001, ANN003
        index = min(self.calls, len(self.payloads) - 1)
        self.calls += 1
        return SimpleNamespace(content=json.dumps(self.payloads[index]))


@pytest.mark.asyncio
async def test_capability_call_compiles_with_contract_inputs() -> None:
    result = await plan_workflow(
        uuid4(),
        "Busca productos de arroz y avísame",
        capabilities=_caps(),
        provider=_Provider([_INTENT, _PLAN]),
        permissions=_PERMS,
    )
    assert result["graph"] is not None, result["issues"]
    node = next(
        item for item in result["graph"]["nodes"] if item["type"] == "capability_call"
    )
    assert node["config"]["capability"] == "catalog.products.search"
    assert node["config"]["inputs"] == {"query": "arroz"}
    assert result["state"] == "DRAFT_READY"


@pytest.mark.asyncio
async def test_capability_call_missing_binding_blocks_and_reports_requirement() -> None:
    result = await plan_workflow(
        uuid4(),
        "Busca productos de arroz y avísame",
        capabilities=_caps(executable=False),
        provider=_Provider([_INTENT, _PLAN]),
        permissions=_PERMS,
    )
    assert result["graph"] is None
    assert result["state"] == "NEEDS_CONFIGURATION"
    assert "capability:catalog.products.search" in {
        item["requirement"] for item in result["requirements"]
    }
    assert any(
        issue["code"] == "capability.unavailable" for issue in result["issues"]
    )


@pytest.mark.asyncio
async def test_capability_call_maps_previous_output_to_input_field() -> None:
    plan = {
        "goal": "Buscar con el texto del trigger",
        "steps": [
            {
                "id": "t",
                "type": "trigger_event",
                "goal": "Mensaje recibido",
                "params": {"event_type": "conversation.message"},
            },
            {
                "id": "c",
                "type": "capability_call",
                "goal": "Buscar productos",
                "depends_on": ["t"],
                "inputs": [{"step": "t", "field": "text", "to": "query"}],
                "params": {"capability": "catalog.products.search"},
            },
        ],
    }
    result = await plan_workflow(
        uuid4(),
        "Busca el producto que pide el cliente",
        capabilities=_caps(),
        provider=_Provider([_INTENT, plan]),
        permissions=_PERMS,
    )
    assert result["graph"] is not None, result["issues"]
    node = next(
        item for item in result["graph"]["nodes"] if item["type"] == "capability_call"
    )
    assert node["config"]["inputs"]["query"].startswith("{{nodes.")
    assert node["config"]["inputs"]["query"].endswith(".output.text}}")


def test_refs_for_plan_extracts_capability_and_action_refs() -> None:
    plan = SemanticPlan.model_validate(
        {
            "goal": "x",
            "steps": [
                {"id": "t", "type": "trigger_manual", "goal": "manual"},
                {
                    "id": "c",
                    "type": "capability_call",
                    "goal": "buscar",
                    "depends_on": ["t"],
                    "params": {"capability": "catalog.products.search"},
                },
                {
                    "id": "i",
                    "type": "integration_action",
                    "goal": "verificar",
                    "depends_on": ["t"],
                    "params": {"action_id": "peru.taxpayer.lookup"},
                },
                {
                    "id": "a",
                    "type": "agent_analysis",
                    "goal": "analizar",
                    "depends_on": ["t"],
                    "params": {"agent_id": "ag-1"},
                },
            ],
        }
    )
    assert refs_for_plan(plan) == [
        "agent.ag-1",
        "catalog.products.search",
        "peru.taxpayer.lookup",
    ]


async def _workspace(org: dict):
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM workspaces WHERE organization_id = :oid "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"oid": org["organization_id"]},
            )
        ).fetchone()
        return row.id if row else None
    finally:
        await session.close()


async def _install(org: dict, slug: str) -> str:
    workspace_id = await _workspace(org)
    result = await install_integration(
        UUID_ORG(org), slug, workspace_id=workspace_id
    )
    return str(result["install_id"])


def UUID_ORG(org: dict):
    from uuid import UUID

    return UUID(str(org["organization_id"]))


async def _bump_action(action_id: str, *, delta: int = 1) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE integration_actions SET version = version + :d "
                "WHERE action_id = :aid"
            ),
            {"d": delta, "aid": action_id},
        )
        await session.commit()
    finally:
        await session.close()


async def _plan_via_api(async_client: AsyncClient, org: dict, plan: dict):
    from src.api.deps import get_llm_provider
    from src.api.main import app

    app.dependency_overrides[get_llm_provider] = lambda: _Provider([_INTENT, plan])
    try:
        return await async_client.post(
            "/api/v1/workflows/architect/plan",
            headers={**_headers(org), "Idempotency-Key": f"cap-{uuid4().hex}"},
            json={"prompt": "Busca productos de arroz y avisa al equipo"},
        )
    finally:
        app.dependency_overrides.pop(get_llm_provider, None)


_INTEGRATION_PLAN = {
    "goal": "Verificar contribuyente y avisar",
    "steps": [
        {"id": "t", "type": "trigger_manual", "goal": "Inicio manual"},
        {
            "id": "i",
            "type": "integration_action",
            "goal": "Verificar RUC",
            "depends_on": ["t"],
            "params": {"action_id": "demo.echo", "inputs": {"text": "hola"}},
        },
        {
            "id": "n",
            "type": "notify",
            "goal": "Avisar",
            "depends_on": ["i"],
            "params": {"channel": "in_app", "title": "Listo", "message": "Verificado"},
        },
    ],
}


@pytest.mark.asyncio
async def test_draft_rejects_stale_capability_snapshot(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Snapshot Stale")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    await _install(org, "demo-echo")

    planned = await _plan_via_api(async_client, org, _INTEGRATION_PLAN)
    assert planned.status_code == 200, planned.text
    body = planned.json()
    snapshot_hash = body["capability_snapshot"]["snapshot_hash"]
    assert snapshot_hash

    await _bump_action("demo.echo")
    try:
        saved = await async_client.post(
            "/api/v1/workflows/architect/draft",
            headers={**_headers(org), "Idempotency-Key": f"stale-{uuid4().hex}"},
            json={
                "plan": body["plan"],
                "plan_hash": body["plan_hash"],
                "capability_snapshot_hash": snapshot_hash,
                "name": "Verificación con snapshot viejo",
            },
        )
        assert saved.status_code == 409, saved.text
        payload = saved.json()
        assert payload["error_code"] == "CAPABILITY_SNAPSHOT_STALE"
        assert "demo.echo" in payload["changed_refs"]
    finally:
        await _bump_action("demo.echo", delta=-1)


@pytest.mark.asyncio
async def test_draft_allows_unrelated_catalog_changes(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Snapshot Unrelated")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    notify_plan = {
        "goal": "Avisar algo",
        "steps": [
            {"id": "t", "type": "trigger_manual", "goal": "Inicio manual"},
            {
                "id": "n",
                "type": "notify",
                "goal": "Avisar",
                "depends_on": ["t"],
                "params": {"channel": "in_app", "title": "Aviso", "message": "Hola"},
            },
        ],
    }
    planned = await _plan_via_api(async_client, org, notify_plan)
    assert planned.status_code == 200, planned.text
    body = planned.json()
    # Cambia el catálogo (otra capacidad), pero el plan no usa esa capacidad.
    await _install(org, "demo-echo")
    saved = await async_client.post(
        "/api/v1/workflows/architect/draft",
        headers={**_headers(org), "Idempotency-Key": f"unrel-{uuid4().hex}"},
        json={
            "plan": body["plan"],
            "plan_hash": body["plan_hash"],
            "capability_snapshot_hash": body["capability_snapshot"]["snapshot_hash"],
            "name": "Aviso simple",
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["workflow_id"]

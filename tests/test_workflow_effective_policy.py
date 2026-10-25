from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.test_workflow_graph import _edge, _graph, _node
from tests.test_workflows import _create_org, _headers, _owner_session


@dataclass
class _Execution:
    permissions: frozenset[str] = frozenset(
        {"workflows:run", "external_actions:execute", "agents:execute"}
    )
    organization_id: str = field(default_factory=lambda: str(uuid4()))
    workspace_id: str | None = None
    actor_type: str = "user"
    actor_id: str | None = None
    correlation_id: str = "test"
    effective_policy: object | None = None


@dataclass
class _Rctx:
    execution: _Execution = field(default_factory=_Execution)
    organization_id: str = field(default_factory=lambda: str(uuid4()))
    simulate: bool = False


@dataclass
class _Node:
    id: str
    type: str
    config: dict


@dataclass
class _NodeDef:
    capabilities: frozenset[str] = frozenset()


def _policy(
    *,
    scope: set[str],
    safety_profile: str = "standard",
    role_bindings: dict | None = None,
    approval_required: bool = False,
    revoked: set[str] | None = None,
):
    from src.platform.workflows.effective_policy import EffectiveExecutionPolicy

    return EffectiveExecutionPolicy(
        organization_id=str(uuid4()),
        workspace_id=None,
        workflow_id=str(uuid4()),
        actor_id=None,
        actor_type="user",
        rbac_scopes=frozenset(
            {"workflows:run", "external_actions:execute", "agents:execute"}
        ),
        capability_scope=frozenset(scope),
        role_bindings=role_bindings or {},
        safety_profile=safety_profile,
        approval_required=approval_required,
        revoked_capabilities=frozenset(revoked or ()),
        policy_version="v1",
    ).with_hash()


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


@pytest.mark.asyncio
async def test_capability_call_without_agent_denied_by_workflow_scope() -> None:
    from src.platform.workflows.policy_enforcement import authorize_node

    verdict = await authorize_node(
        _Rctx(),
        _Node("pay", "capability_call", {"capability": "payments.checkout.create"}),
        _NodeDef(),
        policy=_policy(scope={"catalog.products.search"}),
    )
    assert verdict.allowed is False
    assert verdict.code == "policy.scope_exceeded"
    assert verdict.effective_scope_hash


@pytest.mark.asyncio
async def test_wellness_without_agent_denied() -> None:
    from src.platform.workflows.policy_enforcement import authorize_node

    verdict = await authorize_node(
        _Rctx(),
        _Node("diagnose", "capability_call", {"capability": "clinical.diagnose"}),
        _NodeDef(),
        policy=_policy(scope={"clinical.diagnose"}, safety_profile="wellness"),
    )
    assert verdict.allowed is False
    assert verdict.code == "policy.denied"
    assert "bienestar" in " ".join(verdict.reasons)


@pytest.mark.asyncio
async def test_revoked_capability_denied() -> None:
    from src.platform.workflows.policy_enforcement import authorize_node

    verdict = await authorize_node(
        _Rctx(),
        _Node("search", "capability_call", {"capability": "catalog.products.search"}),
        _NodeDef(),
        policy=_policy(
            scope={"catalog.products.search"},
            revoked={"catalog.products.search"},
        ),
    )
    assert verdict.allowed is False
    assert verdict.code == "policy.revoked"


@pytest.mark.asyncio
async def test_two_agents_do_not_union_privileges() -> None:
    from src.platform.studio.templates import role_template
    from src.platform.workflows.policy_enforcement import authorize_node

    role_a = role_template("sales_advisor").model_dump(mode="json", by_alias=True)
    role_b = role_template("auditor").model_dump(mode="json", by_alias=True)
    role_a["allowed_capabilities"] = ["catalog.products.search"]
    role_b["allowed_capabilities"] = ["knowledge_query"]
    role_b["denied_capabilities"] = ["payments.checkout.create"]
    policy = _policy(
        scope={"catalog.products.search", "payments.checkout.create"},
        role_bindings={"agent-a": role_a, "agent-b": role_b},
    )
    allowed = await authorize_node(
        _Rctx(),
        _Node(
            "search",
            "capability_call",
            {"capability": "catalog.products.search", "agent_id": "agent-a"},
        ),
        _NodeDef(),
        policy=policy,
    )
    denied = await authorize_node(
        _Rctx(),
        _Node(
            "pay",
            "capability_call",
            {"capability": "payments.checkout.create", "agent_id": "agent-b"},
        ),
        _NodeDef(),
        policy=policy,
    )
    assert allowed.allowed is True
    assert denied.allowed is False


@pytest.mark.asyncio
async def test_simulation_applies_same_policy() -> None:
    from src.platform.workflows.policy_enforcement import authorize_node

    ctx = _Rctx()
    ctx.simulate = True
    verdict = await authorize_node(
        ctx,
        _Node("pay", "capability_call", {"capability": "payments.checkout.create"}),
        _NodeDef(),
        policy=_policy(scope={"catalog.products.search"}),
    )
    assert verdict.allowed is False


@pytest.mark.asyncio
async def test_solution_role_denies_injected_capability_without_agent(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Policy Solution")
    binding = await async_client.put(
        "/api/v1/workflows/capability-bindings/catalog.products.search",
        headers=_headers(org),
        json={
            "provider_kind": "rest_api",
            "config": {"url": "https://catalog.example.com/search", "method": "GET"},
        },
    )
    assert binding.status_code == 200, binding.text

    brief = {"brief": "Quiero un vendedor que busque productos en el catálogo"}
    compiled = await async_client.post(
        "/api/v1/studio/solutions/compile", headers=_headers(org), json=brief
    )
    assert compiled.status_code == 200, compiled.text
    materialized = await async_client.post(
        "/api/v1/studio/solutions/materialize",
        headers=_headers(org),
        json={**brief, "confirm": True, "idempotency_key": f"p13-{uuid4().hex}"},
    )
    assert materialized.status_code == 200, materialized.text
    assert materialized.json()["status"] == "READY", materialized.text
    workflow_id = materialized.json()["artifacts"]["workflow"]["id"]

    injected = _graph(
        nodes=[
            _node("t", "trigger_webhook"),
            _node(
                "pay",
                "capability_call",
                {"capability": "payments.checkout.create", "inputs": {}},
            ),
            _node("end", "end"),
        ],
        edges=[_edge("e1", "t", "pay"), _edge("e2", "pay", "end")],
        entrypoints=["t"],
    )
    patched = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers=_headers(org),
        json={"graph": injected, "workflow_version": 2},
    )
    assert patched.status_code == 200, patched.text

    run = await async_client.post(
        f"/api/v1/workflows/{workflow_id}/run",
        headers=_headers(org),
        json={"payload": {}},
    )
    assert run.status_code == 200, run.text
    run_detail = await async_client.get(
        f"/api/v1/workflows/runs/{run.json()['run_id']}", headers=_headers(org)
    )
    assert run_detail.status_code == 200, run_detail.text
    pay = next(
        step for step in run_detail.json()["steps"] if step.get("node_id") == "pay"
    )
    assert pay["status"] == "denied"
    assert pay["output"]["policy_code"] == "policy.scope_exceeded"


@pytest.mark.asyncio
async def test_workflow_by_id_is_not_visible_from_other_workspace(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P13 Policy Workspace")
    created = await async_client.post(
        "/api/v1/workflows",
        headers=_headers(org),
        json={
            "name": "Solo workspace A",
            "trigger_type": "webhook",
            "graph": _graph(
                nodes=[_node("t", "trigger_webhook"), _node("end", "end")],
                edges=[_edge("e1", "t", "end")],
                entrypoints=["t"],
            ),
            "workflow_version": 2,
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    workspace = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Workspace B"}
    )
    assert workspace.status_code == 201, workspace.text
    headers_b = {**_headers(org), "X-Workspace-Id": workspace.json()["id"]}

    response = await async_client.get(
        f"/api/v1/workflows/{workflow_id}", headers=headers_b
    )
    assert response.status_code == 404, response.text
    response = await async_client.get(
        f"/api/v1/workflows/{workflow_id}/versions", headers=headers_b
    )
    assert response.status_code == 404, response.text
    response = await async_client.patch(
        f"/api/v1/workflows/{workflow_id}",
        headers=headers_b,
        json={"name": "intruso"},
    )
    assert response.status_code == 404, response.text

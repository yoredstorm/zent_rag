from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from httpx import AsyncClient

from src.core.domain.memory import MemoryRecord, MemoryStatus, MemoryType
from tests.test_role_profiles import _role_payload
from tests.test_workflow_agent_context import _edge, _FakeRuntime, _graph, _node, _run
from tests.test_workflows import _create_org, _headers, _owner_session


async def _org(client: AsyncClient, name: str) -> dict:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(client, org["organization_id"])
    return org


def _ws_headers(org: dict, workspace_id: str) -> dict:
    return {**_headers(org), "X-Workspace-Id": workspace_id}


async def _default_workspace(client: AsyncClient, org: dict) -> dict:
    listing = await client.get("/api/v1/workspaces", headers=_headers(org))
    assert listing.status_code == 200, listing.text
    return next(w for w in listing.json()["workspaces"] if w["slug"] == "default")


async def _insert_memory(
    *,
    org: dict,
    workspace_id: str,
    scope: str = "long_term_consent",
    subject_id: str | None = "participant-1",
    consent: bool = True,
    title: str = "Progreso",
) -> str:
    from src.infrastructure.postgres.memory_store import PostgresMemoryRepository

    now = datetime.now(timezone.utc)
    record = MemoryRecord(
        organization_id=org["organization_id"],
        memory_type=MemoryType.OPERATIONAL,
        title=title,
        description="detalle que no debe salir sin política",
        pattern_key=f"p06_{uuid4().hex[:8]}",
        pattern_signature=f"p06_{uuid4().hex}",
        status=MemoryStatus.ACTIVE,
        confidence=0.9,
        workspace_id=workspace_id,
        subject_id=subject_id,
        scope=scope,
        consent_at=now if consent else None,
        expires_at=now + timedelta(days=30),
    )
    await PostgresMemoryRepository().insert(record)
    return str(record.id)


@pytest.mark.asyncio
async def test_memory_workspace_isolated_on_list_and_detail(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P06 Memory WS")
    ws_a = await _default_workspace(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Memoria B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    memory_id = await _insert_memory(org=org, workspace_id=ws_a["id"])

    listed_b = await async_client.get(
        "/api/v1/memory", headers=_ws_headers(org, ws_b["id"])
    )
    assert listed_b.status_code == 200, listed_b.text
    assert memory_id not in {item["id"] for item in listed_b.json()["items"]}

    detail_b = await async_client.get(
        f"/api/v1/memory/{memory_id}", headers=_ws_headers(org, ws_b["id"])
    )
    assert detail_b.status_code == 404

    detail_a = await async_client.get(
        f"/api/v1/memory/{memory_id}", headers=_ws_headers(org, ws_a["id"])
    )
    assert detail_a.status_code == 200, detail_a.text
    assert detail_a.json()["workspace_id"] == ws_a["id"]


@pytest.mark.asyncio
async def test_revoke_consent_and_delete_erase_memory(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P06 Consent")
    ws = await _default_workspace(async_client, org)
    memory_id = await _insert_memory(org=org, workspace_id=ws["id"])

    revoked = await async_client.post(
        f"/api/v1/memory/{memory_id}/consent/revoke",
        headers=_ws_headers(org, ws["id"]),
        json={"reason": "el usuario retiró el consentimiento"},
    )
    assert revoked.status_code == 200, revoked.text
    body = revoked.json()
    assert body["consent_at"] is None
    assert body["deleted_at"] is not None
    assert body["status"] == "expired"

    deleted = await async_client.request(
        "DELETE",
        f"/api/v1/memory/{memory_id}",
        headers=_ws_headers(org, ws["id"]),
        json={"reason": "derecho al olvido"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["title"] == "[eliminado]"
    assert deleted.json()["description"] == ""


@pytest.mark.asyncio
async def test_agent_prompt_receives_only_role_scoped_memory(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P06 Agent Prompt")
    ws = await _default_workspace(async_client, org)
    memory_id = await _insert_memory(
        org=org,
        workspace_id=ws["id"],
        scope="workspace",
        subject_id=None,
        title="Contexto local",
    )
    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={
            "name": f"Agente prompt {uuid4().hex[:6]}",
            "system_prompt": "responde",
            "tools": ["search_knowledge"],
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    role_payload = _role_payload("mentor", status="active")
    role_payload["memory_policy"] = {"scope": "workspace"}
    role_payload["allowed_tools"] = ["search_knowledge"]
    role = await async_client.post(
        "/api/v1/studio/roles", headers=_headers(org), json={"role": role_payload}
    )
    assert role.status_code == 201, role.text
    linked = await async_client.post(
        f"/api/v1/studio/agents/{agent_id}/role",
        headers=_headers(org),
        json={"role_profile_id": role.json()["role"]["record_id"]},
    )
    assert linked.status_code == 200, linked.text

    runtime = _FakeRuntime()
    graph = _graph(
        [
            _node("t", "trigger_webhook"),
            _node("ask", "llm", {"agent_id": agent_id, "prompt": "Analiza"}),
        ],
        [_edge("e1", "t", "ask")],
        ["t"],
    )
    await _run(async_client, org, graph, runtime=runtime)
    assert runtime.requests
    context = runtime.requests[0].context or {}
    assert [item["memory_id"] for item in context.get("memory", [])] == [memory_id]


@pytest.mark.asyncio
async def test_agent_context_applies_role_policy_and_workspace(
    async_client: AsyncClient,
) -> None:
    org = await _org(async_client, "P06 Agent Context")
    ws_a = await _default_workspace(async_client, org)
    created = await async_client.post(
        "/api/v1/workspaces", headers=_headers(org), json={"name": "Agente B"}
    )
    assert created.status_code == 201, created.text
    ws_b = created.json()
    subject = "participant-ctx"
    memory_id = await _insert_memory(
        org=org,
        workspace_id=ws_a["id"],
        subject_id=subject,
        title="Progreso consentido",
    )

    agent = await async_client.post(
        "/api/v1/agents",
        headers=_headers(org),
        json={
            "name": f"Agente memoria {uuid4().hex[:6]}",
            "system_prompt": "acompaña",
            "tools": ["search_knowledge"],
        },
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    role_payload = _role_payload("mentor", status="active")
    role = await async_client.post(
        "/api/v1/studio/roles", headers=_headers(org), json={"role": role_payload}
    )
    assert role.status_code == 201, role.text
    linked = await async_client.post(
        f"/api/v1/studio/agents/{agent_id}/role",
        headers=_headers(org),
        json={"role_profile_id": role.json()["role"]["record_id"]},
    )
    assert linked.status_code == 200, linked.text

    context = await async_client.get(
        f"/api/v1/memory/agents/{agent_id}/context",
        headers=_ws_headers(org, ws_a["id"]),
        params={"subject_id": subject},
    )
    assert context.status_code == 200, context.text
    body = context.json()
    assert body["policy"] == "long_term_consent"
    assert [item["memory_id"] for item in body["items"]] == [memory_id]
    assert "description" not in body["items"][0]

    other_workspace = await async_client.get(
        f"/api/v1/memory/agents/{agent_id}/context",
        headers=_ws_headers(org, ws_b["id"]),
        params={"subject_id": subject},
    )
    assert other_workspace.status_code == 200, other_workspace.text
    assert other_workspace.json()["items"] == []

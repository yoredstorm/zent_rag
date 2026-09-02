# =============================================================================
# Workspaces — CRUD, default auto-creado, aislamiento tenant, permisos
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ws-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


@pytest.mark.asyncio
async def test_default_workspace_auto_created_and_crud(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "WS Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    # GET auto-crea el default.
    listing = await async_client.get("/api/v1/workspaces", headers=h)
    assert listing.status_code == 200, listing.text
    workspaces = listing.json()["workspaces"]
    assert any(w["slug"] == "default" for w in workspaces)

    # Crear workspace.
    created = await async_client.post(
        "/api/v1/workspaces", headers=h, json={"name": "Production AI"}
    )
    assert created.status_code == 201, created.text
    ws = created.json()
    assert ws["slug"] == "production-ai"
    assert ws["status"] == "active"
    assert ws["counts"] == {"agents": 0, "kbs": 0, "connectors": 0}

    # Slug duplicado → 409.
    dup = await async_client.post(
        "/api/v1/workspaces", headers=h, json={"name": "Production AI"}
    )
    assert dup.status_code == 409, dup.text

    # Update + archive.
    updated = await async_client.put(
        f"/api/v1/workspaces/{ws['id']}",
        headers=h,
        json={"description": "Espacio de producción"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "Espacio de producción"

    archived = await async_client.delete(f"/api/v1/workspaces/{ws['id']}", headers=h)
    assert archived.status_code == 200, archived.text
    fetched = await async_client.get(f"/api/v1/workspaces/{ws['id']}", headers=h)
    assert fetched.json()["status"] == "archived"


@pytest.mark.asyncio
async def test_agent_kb_connector_accept_workspace_id(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "WS Owner Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    ws = (
        await async_client.post(
            "/api/v1/workspaces", headers=h, json={"name": "Dev"}
        )
    ).json()

    agent = await async_client.post(
        "/api/v1/agents",
        headers=h,
        json={
            "name": "WS Agent",
            "workspace_id": ws["id"],
            "system_prompt": "test",
            "tools": ["search_knowledge"],
        },
    )
    assert agent.status_code == 201, agent.text
    assert agent.json()["workspace_id"] == ws["id"]

    kb = await async_client.post(
        "/api/v1/knowledge-bases",
        headers=h,
        json={"name": "WS KB", "workspace_id": ws["id"]},
    )
    assert kb.status_code == 201, kb.text

    connector = await async_client.post(
        "/api/v1/connectors",
        headers=h,
        json={"name": "WS Conn", "type": "postgres", "workspace_id": ws["id"], "config": {}},
    )
    assert connector.status_code == 201, connector.text

    # Counts reflejan lo creado.
    listing = await async_client.get(f"/api/v1/workspaces/{ws['id']}", headers=h)
    counts = listing.json()["counts"]
    assert counts["agents"] == 1
    assert counts["kbs"] == 1
    assert counts["connectors"] == 1


@pytest.mark.asyncio
async def test_workspace_isolation_cross_tenant(
    async_client: AsyncClient,
) -> None:
    org_a = await _create_org(async_client, "WS Iso A")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b = await _create_org(async_client, "WS Iso B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    h_a, h_b = _headers(org_a), _headers(org_b)

    ws_a = (
        await async_client.post(
            "/api/v1/workspaces", headers=h_a, json={"name": "Secret Space"}
        )
    ).json()

    # B no ve el workspace de A (404, no leak).
    resp = await async_client.get(f"/api/v1/workspaces/{ws_a['id']}", headers=h_b)
    assert resp.status_code == 404, resp.text
    resp = await async_client.put(
        f"/api/v1/workspaces/{ws_a['id']}", headers=h_b, json={"name": "hack"}
    )
    assert resp.status_code == 404, resp.text
    resp = await async_client.delete(f"/api/v1/workspaces/{ws_a['id']}", headers=h_b)
    assert resp.status_code == 404, resp.text

    # B no puede crear un agente en el workspace de A.
    bad = await async_client.post(
        "/api/v1/agents",
        headers=h_b,
        json={
            "name": "Cross Agent",
            "workspace_id": ws_a["id"],
            "system_prompt": "test",
            "tools": [],
        },
    )
    assert bad.status_code == 404, bad.text


@pytest.mark.asyncio
async def test_workspace_permissions_scoped_key(
    async_client: AsyncClient,
) -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    org = await _create_org(async_client, "WS Perms Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    token = await billing.create_api_key(
        UUID(org["organization_id"]), name="rag-only", scopes=["rag:read"], created_by=None
    )
    limited = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }
    resp = await async_client.get("/api/v1/workspaces", headers=limited)
    assert resp.status_code == 403, resp.text
    resp = await async_client.post(
        "/api/v1/workspaces", headers=limited, json={"name": "x"}
    )
    assert resp.status_code == 403, resp.text

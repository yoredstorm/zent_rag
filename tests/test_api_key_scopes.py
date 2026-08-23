# =============================================================================
# API key scopes — allowlist, aliases, enforcement on chat / connectors / usage
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Scope Co {uuid4().hex[:8]}",
            "email": f"sc-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


async def _create_key(
    client: AsyncClient, org: dict, scopes: list[str], name: str = "scoped"
) -> str:
    session = await _owner_session(org["organization_id"])
    resp = await client.post(
        "/api/v1/organizations/api-keys",
        json={"name": name, "scopes": scopes},
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _bearer(token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": organization_id,
    }


@pytest.mark.asyncio
async def test_trial_token_uses_zent_prefix(async_client: AsyncClient) -> None:
    org = await _trial(async_client)
    assert org["api_token"].startswith("zent_sk_live_")


@pytest.mark.asyncio
async def test_legacy_rag_query_scope_can_chat(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    token = await _create_key(
        async_client, org, ["rag:query", "rag:ingest"], name="legacy"
    )
    resp = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers=_bearer(token, org["organization_id"]),
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_key_without_rag_read_cannot_chat(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    token = await _create_key(async_client, org, ["usage:read"], name="usage-only")
    resp = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers=_bearer(token, org["organization_id"]),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_connectors_read_scope_lists_connectors(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    token = await _create_key(
        async_client, org, ["connectors:read"], name="conn-read"
    )
    listed = await async_client.get(
        "/api/v1/connectors",
        headers=_bearer(token, org["organization_id"]),
    )
    assert listed.status_code == 200, listed.text
    created = await async_client.post(
        "/api/v1/connectors",
        json={"name": "blocked", "type": "postgres", "config": {}},
        headers=_bearer(token, org["organization_id"]),
    )
    assert created.status_code == 403, created.text


@pytest.mark.asyncio
async def test_usage_read_scope_reads_usage(async_client: AsyncClient) -> None:
    org = await _trial(async_client)
    token = await _create_key(async_client, org, ["usage:read"], name="usage")
    resp = await async_client.get(
        "/api/v1/billing/usage",
        headers=_bearer(token, org["organization_id"]),
        params={"days": 7},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_admin_star_rejected_on_create(async_client: AsyncClient) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.post(
        "/api/v1/organizations/api-keys",
        json={"name": "evil", "scopes": ["admin:*"]},
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_run_agent_requires_agents_execute(
    async_client: AsyncClient,
) -> None:
    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from tests.test_agent_api import _FakeRuntime

    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    owner = {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org["organization_id"],
    }
    chat_token = await _create_key(async_client, org, ["rag:read"], name="chat-only")

    app.dependency_overrides[get_agent_runtime] = lambda: _FakeRuntime()
    try:
        create = await async_client.post(
            "/api/v1/agents",
            json={"name": f"agent-{uuid4().hex[:8]}", "tools": []},
            headers=owner,
        )
        assert create.status_code == 201, create.text
        agent_id = create.json()["id"]
        denied = await async_client.post(
            f"/api/v1/agents/{agent_id}/run",
            json={"message": "hola"},
            headers=_bearer(chat_token, org["organization_id"]),
        )
        assert denied.status_code == 403, denied.text
    finally:
        app.dependency_overrides.clear()

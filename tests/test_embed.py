# =============================================================================
# Embed widget — public token, origin allowlist, tenant isolation
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.billing.entitlements import upsert_plan_entitlements

TRIAL_PLAN_ID = UUID("10000000-0000-0000-0000-000000000001")


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"emb-{uuid4().hex[:8]}@example.com",
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


def _headers(org: dict) -> dict:
    return {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }


async def _enable_embed() -> None:
    await upsert_plan_entitlements(
        TRIAL_PLAN_ID,
        [{"key": "embed_widget", "value_type": "bool", "value_bool": True}],
    )


async def _disable_embed() -> None:
    await upsert_plan_entitlements(
        TRIAL_PLAN_ID,
        [{"key": "embed_widget", "value_type": "bool", "value_bool": False}],
    )


async def _org_with_agent(client: AsyncClient, name: str) -> tuple[dict, str]:
    org = await _create_org(client, name)
    org["session"] = await _owner_session(org["organization_id"])
    create = await client.post(
        "/api/v1/agents",
        json={"name": f"emb-agent-{uuid4().hex[:8]}", "tools": ["search_knowledge"]},
        headers=_headers(org),
    )
    assert create.status_code == 201, create.text
    return org, create.json()["id"]


@pytest.mark.asyncio
async def test_create_embed_token_requires_entitlement(
    async_client: AsyncClient,
) -> None:
    await _disable_embed()
    org, agent_id = await _org_with_agent(async_client, "Embed Denied Org")
    try:
        resp = await async_client.post(
            f"/api/v1/agents/{agent_id}/embed/token",
            json={"allowed_origins": ["https://farmacia.cl"]},
            headers=_headers(org),
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _disable_embed()


@pytest.mark.asyncio
async def test_embed_chat_rejects_origin_not_allowlisted(
    async_client: AsyncClient,
) -> None:
    await _enable_embed()
    try:
        org, agent_id = await _org_with_agent(async_client, "Embed Origin Org")
        minted = await async_client.post(
            f"/api/v1/agents/{agent_id}/embed/token",
            json={"allowed_origins": ["https://farmacia.cl"]},
            headers=_headers(org),
        )
        assert minted.status_code == 201, minted.text
        public_id = minted.json()["public_id"]
        assert minted.json()["token"].startswith("zent_emb_")
        assert "token" not in str(minted.json()["public_id"])

        resp = await async_client.post(
            f"/api/v1/embed/{public_id}/chat",
            json={"messages": [{"role": "user", "content": "hola"}]},
            headers={"Origin": "https://evil.example"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _disable_embed()


@pytest.mark.asyncio
async def test_revoked_embed_token_returns_401(async_client: AsyncClient) -> None:
    await _enable_embed()
    try:
        org, agent_id = await _org_with_agent(async_client, "Embed Revoke Org")
        minted = await async_client.post(
            f"/api/v1/agents/{agent_id}/embed/token",
            json={"allowed_origins": ["https://farmacia.cl"]},
            headers=_headers(org),
        )
        assert minted.status_code == 201, minted.text
        public_id = minted.json()["public_id"]

        revoke = await async_client.post(
            f"/api/v1/agents/{agent_id}/embed/revoke",
            headers=_headers(org),
        )
        assert revoke.status_code == 200, revoke.text

        resp = await async_client.post(
            f"/api/v1/embed/{public_id}/chat",
            json={"messages": [{"role": "user", "content": "hola"}]},
            headers={"Origin": "https://farmacia.cl"},
        )
        assert resp.status_code == 401, resp.text
    finally:
        await _disable_embed()


@pytest.mark.asyncio
async def test_embed_token_cannot_run_foreign_agent(
    async_client: AsyncClient,
) -> None:
    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _Capture:
        def __init__(self) -> None:
            self.last_request = None

        async def run(self, request):
            self.last_request = request
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer="ok",
                message=request.message,
            )

    await _enable_embed()
    fake = _Capture()
    app.dependency_overrides[get_agent_runtime] = lambda: fake
    try:
        org_a, agent_a = await _org_with_agent(async_client, "Embed Org A")
        org_b, agent_b = await _org_with_agent(async_client, "Embed Org B")
        minted = await async_client.post(
            f"/api/v1/agents/{agent_a}/embed/token",
            json={"allowed_origins": ["https://farmacia.cl"]},
            headers=_headers(org_a),
        )
        assert minted.status_code == 201, minted.text
        public_id = minted.json()["public_id"]

        resp = await async_client.post(
            f"/api/v1/embed/{public_id}/chat",
            json={
                "messages": [{"role": "user", "content": "hola"}],
                "agent_id": agent_b,
                "organization_id": org_b["organization_id"],
            },
            headers={"Origin": "https://farmacia.cl"},
        )
        assert resp.status_code == 200, resp.text
        assert fake.last_request is not None
        assert str(fake.last_request.agent.id) == agent_a
        assert str(fake.last_request.agent.organization_id) == org_a["organization_id"]
        assert str(fake.last_request.agent.id) != agent_b
    finally:
        app.dependency_overrides.clear()
        await _disable_embed()

# =============================================================================
# Usage API — metrics endpoints, pricing CRUD, alerts (admin org)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"us-{uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_usage_endpoint_includes_cost(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Usage API Org")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.get(
        "/api/v1/billing/usage", headers=_headers(org), params={"days": 30}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "estimated_cost" in data["totals"]


@pytest.mark.asyncio
async def test_usage_by_agent_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Usage API Org 2")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.get(
        "/api/v1/billing/usage/agents", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    assert "agents" in resp.json()


@pytest.mark.asyncio
async def test_usage_by_api_key_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Usage API Org 3")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.get(
        "/api/v1/billing/usage/api-keys", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    assert "api_keys" in resp.json()


@pytest.mark.asyncio
async def test_storage_endpoint(async_client: AsyncClient) -> None:
    from src.core.config import get_settings

    if get_settings().ENVIRONMENT != "development":
        pytest.skip("Requiere Qdrant real")

    org = await _create_org(async_client, "Usage API Org 4")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.get(
        "/api/v1/billing/usage/storage", headers=_headers(org)
    )
    assert resp.status_code == 200, resp.text
    assert "vector_points" in resp.json()


@pytest.mark.asyncio
async def test_pricing_crud(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Usage API Org 5")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    listing = await async_client.get("/api/v1/billing/pricing", headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["count"] >= 1

    model = f"usage-test-model-{uuid4().hex[:6]}"
    update = await async_client.put(
        "/api/v1/billing/pricing",
        json={
            "provider": "test",
            "model": model,
            "input_cost_per_1k": 0.001,
            "output_cost_per_1k": 0.002,
            "embedding_cost_per_1k": 0.0001,
        },
        headers=headers,
    )
    assert update.status_code == 200, update.text

    listing2 = await async_client.get("/api/v1/billing/pricing", headers=headers)
    models = {p["model"] for p in listing2.json()["prices"]}
    assert model in models


@pytest.mark.asyncio
async def test_alerts_endpoints(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Usage API Org 6")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    listing = await async_client.get(
        "/api/v1/billing/usage/alerts", headers=headers
    )
    assert listing.status_code == 200, listing.text
    assert "alerts" in listing.json()

    # Ack de alerta inexistente → 404.
    ack = await async_client.post(
        f"/api/v1/billing/usage/alerts/{uuid4()}/ack", headers=headers
    )
    assert ack.status_code == 404, ack.text


@pytest.mark.asyncio
async def test_usage_endpoints_require_auth(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1/billing/usage/agents")
    assert resp.status_code == 401, resp.text

    resp = await async_client.get("/api/v1/billing/pricing")
    assert resp.status_code == 401, resp.text

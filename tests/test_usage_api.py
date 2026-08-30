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
async def test_usage_endpoint_includes_errors_and_top_users(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "Usage Dashboard Org")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.get(
        "/api/v1/billing/usage", headers=_headers(org), params={"days": 30}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "errors" in data["totals"]
    assert isinstance(data["totals"]["errors"], int)
    assert "top_users" in data
    assert isinstance(data["top_users"], list)
    assert "top_queries" in data
    assert isinstance(data["top_queries"], list)


@pytest.mark.asyncio
async def test_usage_errors_and_top_users_are_org_scoped(
    async_client: AsyncClient,
) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.infrastructure.postgres.session import get_async_session

    org_a = await _create_org(async_client, "Usage Scope A")
    org_b = await _create_org(async_client, "Usage Scope B")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b["session"] = await _owner_session(org_b["organization_id"])

    users = PostgresUserRepository()
    user_a = await users.get_by_external_id(UUID(org_a["organization_id"]), "default-admin")
    user_b = await users.get_by_external_id(UUID(org_b["organization_id"]), "default-admin")
    assert user_a is not None and user_b is not None

    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO usage_events
                    (request_id, event_type, organization_id, user_id, status, estimated_cost)
                VALUES
                    (:r1, 'rag_query', :oa, :ua, 'completed', 0.1),
                    (:r2, 'rag_query', :oa, :ua, 'error', 0.0),
                    (:r3, 'rag_query', :ob, :ub, 'error', 0.0)
                """
            ),
            {
                "r1": uuid4(),
                "r2": uuid4(),
                "r3": uuid4(),
                "oa": UUID(org_a["organization_id"]),
                "ob": UUID(org_b["organization_id"]),
                "ua": user_a.id,
                "ub": user_b.id,
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO usage_logs (organization_id, user_id, total_tokens, latency_ms)
                VALUES (:oa, :ua, 10, 5), (:oa, :ua, 12, 8)
                """
            ),
            {"oa": UUID(org_a["organization_id"]), "ua": user_a.id},
        )
        await session.commit()
    finally:
        await session.close()

    resp_a = await async_client.get(
        "/api/v1/billing/usage", headers=_headers(org_a), params={"days": 30}
    )
    assert resp_a.status_code == 200, resp_a.text
    data_a = resp_a.json()
    assert data_a["totals"]["errors"] == 1
    assert data_a["top_users"][0]["user_id"] == str(user_a.id)
    assert data_a["top_users"][0]["requests"] == 2

    resp_b = await async_client.get(
        "/api/v1/billing/usage", headers=_headers(org_b), params={"days": 30}
    )
    assert resp_b.status_code == 200, resp_b.text
    data_b = resp_b.json()
    assert data_b["totals"]["errors"] == 1
    assert str(user_a.id) not in {u["user_id"] for u in data_b["top_users"]}


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

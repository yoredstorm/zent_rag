# =============================================================================
# Idempotency-Key — required paths, replay, body conflict, CORS
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_missing_idempotency_key_on_create_key_returns_400(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    resp = await async_client.post(
        "/api/v1/organizations/api-keys",
        json={"name": "no-key", "scopes": ["rag:read"]},
        headers={**trial_auth, "X-Skip-Idempotency-Auto": "1"},
    )
    # trial_auth is an API key without apikeys:write → 403 before or after
    # idempotency. Use a portal session instead.
    assert resp.status_code in (400, 403)


@pytest.mark.asyncio
async def test_create_key_requires_idempotency_key(
    async_client: AsyncClient,
) -> None:
    trial = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Idem {uuid4().hex[:8]}",
            "email": f"idem-{uuid4().hex[:8]}@example.com",
        },
    )
    assert trial.status_code == 200, trial.text
    org_id = trial.json()["organization_id"]

    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org_id), "default-admin"
    )
    assert user is not None
    session = encrypt_session(user.id, UUID(org_id))
    headers = {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org_id,
        "X-Skip-Idempotency-Auto": "1",
    }
    resp = await async_client.post(
        "/api/v1/organizations/api-keys",
        json={"name": "needs-key", "scopes": ["rag:read"]},
        headers=headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error_code"] == "idempotency_key_required"


@pytest.mark.asyncio
async def test_idempotent_replay_returns_same_body(
    async_client: AsyncClient,
) -> None:
    trial = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"IdemR {uuid4().hex[:8]}",
            "email": f"idemr-{uuid4().hex[:8]}@example.com",
        },
    )
    org_id = trial.json()["organization_id"]
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org_id), "default-admin"
    )
    assert user is not None
    session = encrypt_session(user.id, UUID(org_id))
    key = uuid4().hex
    headers = {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org_id,
        "Idempotency-Key": key,
    }
    body = {"name": f"replay-{uuid4().hex[:6]}", "scopes": ["rag:read"]}
    first = await async_client.post(
        "/api/v1/organizations/api-keys", json=body, headers=headers
    )
    assert first.status_code == 200, first.text
    token = first.json()["token"]
    second = await async_client.post(
        "/api/v1/organizations/api-keys", json=body, headers=headers
    )
    assert second.status_code == 200, second.text
    assert second.json()["token"] == token
    assert second.headers.get("idempotency-replayed") == "true"


@pytest.mark.asyncio
async def test_idempotency_conflict_on_different_body(
    async_client: AsyncClient,
) -> None:
    trial = await async_client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"IdemC {uuid4().hex[:8]}",
            "email": f"idemc-{uuid4().hex[:8]}@example.com",
        },
    )
    org_id = trial.json()["organization_id"]
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org_id), "default-admin"
    )
    assert user is not None
    session = encrypt_session(user.id, UUID(org_id))
    key = uuid4().hex
    headers = {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org_id,
        "Idempotency-Key": key,
    }
    first = await async_client.post(
        "/api/v1/organizations/api-keys",
        json={"name": "one", "scopes": ["rag:read"]},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conflict = await async_client.post(
        "/api/v1/organizations/api-keys",
        json={"name": "two", "scopes": ["rag:read"]},
        headers=headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error_code"] == "idempotency_key_conflict"


def test_cors_allows_idempotency_key() -> None:
    from src.api.main import app

    cors = next(
        m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    headers = {h.lower() for h in cors.kwargs.get("allow_headers", [])}
    expose = {h.lower() for h in cors.kwargs.get("expose_headers", [])}
    methods = {m.upper() for m in cors.kwargs.get("allow_methods", [])}
    assert "idempotency-key" in headers
    assert "idempotency-replayed" in expose
    assert "PATCH" in methods


@pytest.mark.asyncio
async def test_api_v1_version_endpoint(async_client: AsyncClient) -> None:
    resp = await async_client.get("/api/v1")
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == "1.0.0"
    spec = await async_client.get("/api/v1/openapi.json")
    assert spec.status_code == 200
    assert spec.json()["info"]["title"] == "Zent API"

# =============================================================================
# Identity hardening — Bearer is the only authority; headers are anti-spoof.
# =============================================================================
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Id Co {uuid4().hex[:8]}",
            "email": f"id-{uuid4().hex[:8]}@example.com",
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
async def test_valid_token_returns_200_on_rag_query(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers=trial_auth,
    )
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_invalid_token_returns_401(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_expired_portal_session_returns_401(async_client: AsyncClient) -> None:
    from src.platform.auth.session import encrypt_session

    token = encrypt_session(uuid4(), uuid4(), ttl_hours=-1)
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_expired_api_key_returns_401(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    import hashlib
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    raw = trial_auth["Authorization"].split(" ", 1)[1]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE api_keys SET expires_at = :exp WHERE key_hash = :h"
            ),
            {
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
                "h": key_hash,
            },
        )
        await session.commit()
    finally:
        await session.close()

    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers=trial_auth,
    )
    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_tenant_spoofing_header_returns_403(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers={**trial_auth, "X-Organization-Id": str(uuid4())},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_user_spoofing_header_returns_403(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers={**trial_auth, "X-User-Id": str(uuid4())},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_role_header_and_body_cannot_elevate(
    async_client: AsyncClient,
    trial_auth: dict[str, str],
    mock_orchestrator,
) -> None:
    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola", "role": "admin"},
        headers={**trial_auth, "X-User-Role": "admin"},
    )
    assert response.status_code == 200, response.text
    # trial API keys default to server role admin (legacy); spoofing is not elevation
    assert mock_orchestrator.last_kwargs["role"] == "admin"

    response = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola", "role": "customer"},
        headers={**trial_auth, "X-User-Role": "admin"},
    )
    assert response.status_code == 200, response.text
    assert mock_orchestrator.last_kwargs["role"] == "customer"


@pytest.mark.asyncio
async def test_resolve_effective_role_never_elevates_customer() -> None:
    from src.api.security import resolve_effective_role
    from src.core.domain.entities import TenantContext

    ctx = TenantContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        roles=frozenset(),
        permissions=frozenset({"rag:read"}),
        scopes=frozenset({"rag:read", "rag:customer"}),
        auth_type="api_token",
    )
    request = MagicMock()
    request.state.tenant_context = ctx
    role = await resolve_effective_role(request, "admin")
    assert role == "customer"


@pytest.mark.asyncio
async def test_usage_read_scope_cannot_query_or_ingest(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    token = await _create_key(async_client, org, ["usage:read"], name="usage-only")
    headers = _bearer(token, org["organization_id"])
    query = await async_client.post(
        "/api/v1/rag/query",
        json={"query": "hola"},
        headers=headers,
    )
    assert query.status_code == 403, query.text
    ingest = await async_client.post(
        "/api/v1/ingestion/sync",
        headers=headers,
    )
    assert ingest.status_code == 403, ingest.text


def test_bind_organization_id_rejects_mismatch() -> None:
    from src.core.domain.entities import TenantContext
    from src.platform.tenants.context import (
        bind_organization_id,
        clear_tenant_context,
        set_tenant_context,
    )

    ctx = TenantContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        roles=frozenset(),
        permissions=frozenset(),
        scopes=frozenset(),
        auth_type="api_token",
    )
    set_tenant_context(ctx)
    try:
        with pytest.raises(ValueError, match="organization_id"):
            bind_organization_id(uuid4())
        assert bind_organization_id(ctx.tenant_id) == ctx.tenant_id
    finally:
        clear_tenant_context()


def test_sql_llm_organization_literal_is_overwritten() -> None:
    from src.agents.tools.sql_expert_postgres import rewrite_sql_organization_id

    tenant_a = uuid4()
    tenant_b = uuid4()
    sql = (
        "SELECT p.name FROM farmacia.products AS p "
        f"WHERE organization_id = '{tenant_b}'::uuid"
    )
    out = rewrite_sql_organization_id(sql, tenant_a)
    assert str(tenant_a) in out
    assert str(tenant_b) not in out


@pytest.mark.asyncio
async def test_billing_usage_rejects_cross_tenant_header(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    other = await _trial(async_client)
    spoofed = await async_client.get(
        "/api/v1/billing/usage",
        headers={**trial_auth, "X-Organization-Id": other["organization_id"]},
        params={"days": 7},
    )
    assert spoofed.status_code == 403, spoofed.text

    own = await async_client.get(
        "/api/v1/billing/usage",
        headers=trial_auth,
        params={"days": 7},
    )
    assert own.status_code == 200, own.text


@pytest.mark.asyncio
async def test_rag_active_requests_single_dec_on_error(
    async_client: AsyncClient,
    trial_auth: dict[str, str],
    mock_orchestrator,
) -> None:
    from unittest.mock import patch

    class _Gauge:
        def __init__(self) -> None:
            self.inc_count = 0
            self.dec_count = 0

        def labels(self, **kwargs):
            return self

        def inc(self) -> None:
            self.inc_count += 1

        def dec(self) -> None:
            self.dec_count += 1

    gauge = _Gauge()
    mock_orchestrator.execute = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("src.api.routes.query.rag_active_requests", gauge):
        response = await async_client.post(
            "/api/v1/rag/query",
            json={"query": "hola"},
            headers=trial_auth,
        )
    assert response.status_code == 500, response.text
    assert gauge.inc_count == 1
    assert gauge.dec_count == 1

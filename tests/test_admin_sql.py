# =============================================================================
# Tests — Admin SQL endpoint (seguridad): rol admin, solo SELECT, auditoría
# =============================================================================
from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_sql_requires_auth(async_client: AsyncClient) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 1"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_sql_allows_select_with_admin_scope(
    async_client: AsyncClient, dev_api_token: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 1 AS uno, 2 AS dos"},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["columns"] == ["uno", "dos"]
    assert len(data["rows"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "UPDATE farmacia.products SET price = 0",
        "DELETE FROM farmacia.products",
        "INSERT INTO farmacia.products (name) VALUES ('x')",
        "WITH x AS (DELETE FROM farmacia.products RETURNING *) SELECT * FROM x",
        "DROP TABLE farmacia.products",
    ],
)
async def test_admin_sql_rejects_non_select(
    async_client: AsyncClient, dev_api_token: str, query: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": query},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "00000000-0000-0000-0000-000000000001",
        },
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_sql_rejects_non_admin_api_token(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """Un API token normal (rag_live_ sin admin:*) no puede ejecutar SQL."""
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 1"},
        headers={**trial_auth},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_admin_sql_allows_portal_session(
    async_client: AsyncClient, trial_auth: dict[str, str]
) -> None:
    """La sesión del portal (dueño del tenant) sí puede ejecutar SQL."""
    from uuid import UUID as _UUID

    from src.infrastructure.portal_session import encrypt_session

    session_token = encrypt_session(
        user_id=uuid4(),
        tenant_id=_UUID(trial_auth["X-Tenant-Id"]),
    )
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 42 AS respuesta"},
        headers={
            "Authorization": f"Bearer {session_token}",
            "X-Tenant-Id": trial_auth["X-Tenant-Id"],
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["rows"][0]["respuesta"] == "42"


@pytest.mark.asyncio
async def test_admin_sql_rejects_mismatched_tenant_header(
    async_client: AsyncClient, dev_api_token: str
) -> None:
    response = await async_client.post(
        "/api/v1/admin/sql",
        json={"query": "SELECT 1"},
        headers={
            "Authorization": f"Bearer {dev_api_token}",
            "X-Tenant-Id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
        },
    )
    assert response.status_code == 403, response.text

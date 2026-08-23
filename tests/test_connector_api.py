# =============================================================================
# Connector API — create con secrets, test, discover, capabilities, types
# =============================================================================
from __future__ import annotations

from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.connectors.plugin import (
    ConnectionTestResult,
    ConnectorPlugin,
    SchemaDiscovery,
    register_plugin,
)
from src.connectors.plugin.models import ColumnSchema, TableSchema


class _FakeApiPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "fake_api"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["api_key"]

    async def validate(self) -> None:
        if not self.secrets.get("api_key"):
            raise ValueError("missing api_key")

    async def connect(self) -> None:
        pass

    async def test_connection(self) -> ConnectionTestResult:
        await self.validate()
        return ConnectionTestResult(ok=True, latency_ms=1.5, message="ok")

    async def discover(self) -> SchemaDiscovery:
        await self.validate()
        return SchemaDiscovery(
            tables=[TableSchema(name="items", columns=[ColumnSchema(name="id", data_type="int")])],
            source="fake_api",
        )


register_plugin(_FakeApiPlugin)


async def _create_org(client: AsyncClient, name: str) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"cp-{uuid4().hex[:8]}@example.com",
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
async def test_create_connector_with_secrets_never_returns_them(
    async_client: AsyncClient,
) -> None:
    org = await _create_org(async_client, "CP API Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    resp = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": f"api-{uuid4().hex[:8]}",
            "type": "fake_api",
            "config": {"base_url": "https://api.example.com"},
            "secrets": {"api_key": "sk-ultra-secret"},
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["has_secrets"] is True
    blob = str(data)
    assert "sk-ultra-secret" not in blob
    # config en DB no contiene secretos.
    assert "sk-ultra-secret" not in str(data["config"])


@pytest.mark.asyncio
async def test_test_endpoint_returns_ok(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP API Org 2")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": f"api-{uuid4().hex[:8]}",
            "type": "fake_api",
            "config": {"base_url": "https://api.example.com"},
            "secrets": {"api_key": "sk-secret-1"},
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    connector_id = create.json()["id"]

    resp = await async_client.post(
        f"/api/v1/connectors/{connector_id}/test", headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["message"] == "ok"
    assert "sk-secret-1" not in str(data)


@pytest.mark.asyncio
async def test_discover_endpoint_returns_schema(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP API Org 3")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/connectors",
        json={
            "name": f"api-{uuid4().hex[:8]}",
            "type": "fake_api",
            "config": {"base_url": "https://api.example.com"},
            "secrets": {"api_key": "sk-secret-2"},
        },
        headers=headers,
    )
    connector_id = create.json()["id"]

    resp = await async_client.post(
        f"/api/v1/connectors/{connector_id}/discover", headers=headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["source"] == "fake_api"
    assert data["tables"][0]["name"] == "items"


@pytest.mark.asyncio
async def test_capabilities_and_types_endpoints(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP API Org 4")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    create = await async_client.post(
        "/api/v1/connectors",
        json={"name": f"api-{uuid4().hex[:8]}", "type": "fake_api", "config": {}},
        headers=headers,
    )
    connector_id = create.json()["id"]

    caps = await async_client.get(
        f"/api/v1/connectors/{connector_id}/capabilities", headers=headers
    )
    assert caps.status_code == 200, caps.text
    assert caps.json()["type"] == "fake_api"
    assert "test" in caps.json()["capabilities"]
    assert "api_key" in caps.json()["required_secret_keys"]

    types = await async_client.get("/api/v1/connectors/types", headers=headers)
    assert types.status_code == 200, types.text
    type_names = {t["type"] for t in types.json()["types"]}
    assert "fake_api" in type_names
    assert "postgres" in type_names
    assert "mysql" in type_names


@pytest.mark.asyncio
async def test_connector_endpoints_require_permission(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/api/v1/connectors/types")
    assert resp.status_code == 401, resp.text

    resp = await async_client.post(
        f"/api/v1/connectors/{uuid4()}/test"
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_unknown_type_rejected_on_create(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP API Org 5")
    org["session"] = await _owner_session(org["organization_id"])

    resp = await async_client.post(
        "/api/v1/connectors",
        json={"name": f"x-{uuid4().hex[:8]}", "type": "not_a_plugin", "config": {}},
        headers=_headers(org),
    )
    assert resp.status_code == 400, resp.text

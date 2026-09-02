# =============================================================================
# Agent Deployments API — versiones, entornos, deployments, rollback
# =============================================================================
# Integración real (Postgres del stack docker). Cubre flujo completo,
# aislamiento cross-tenant y permisos por scope de API key.
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
            "email": f"dep-{uuid4().hex[:8]}@example.com",
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


async def _create_agent(client: AsyncClient, headers: dict, name: str) -> dict:
    response = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": name,
            "description": "Agente de inventario",
            "system_prompt": "Eres un asistente de inventario.",
            "tools": ["search_knowledge"],
            "model": "gpt-4o-mini",
            "config": {"temperature": 0.1},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_full_version_deploy_rollback_flow(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Deploy Flow Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    agent = await _create_agent(async_client, headers, "Inventory Assistant")

    # 1. Snapshot v1 (draft) y promoción a ready
    created = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions",
        headers=headers,
        json={"notes": "Primera versión"},
    )
    assert created.status_code == 201, created.text
    v1 = created.json()
    assert v1["status"] == "draft"
    assert v1["version_number"] == 1
    assert v1["config_snapshot"]["system_prompt"] == "Eres un asistente de inventario."

    promoted = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v1['id']}/promote",
        headers=headers,
        json={"status": "ready"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == "ready"

    # 2. Snapshot v2
    created2 = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions",
        headers=headers,
        json={},
    )
    assert created2.status_code == 201
    v2 = created2.json()
    assert v2["version_number"] == 2

    # 3. Entornos por defecto auto-creados
    envs = await async_client.get("/api/v1/environments", headers=headers)
    assert envs.status_code == 200, envs.text
    slugs = {e["slug"] for e in envs.json()["environments"]}
    assert {"development", "staging", "production"} <= slugs
    prod = next(e for e in envs.json()["environments"] if e["slug"] == "production")

    # 4. Deploy v1 a production → healthy
    dep = await async_client.post(
        "/api/v1/deployments",
        headers=headers,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v1["id"],
            "environment_id": prod["id"],
        },
    )
    assert dep.status_code == 201, dep.text
    deployment = dep.json()
    assert deployment["status"] == "healthy"
    assert deployment["agent_version_id"] == v1["id"]
    assert deployment["slug"] == "inventory-assistant-production"
    assert deployment["endpoint"] == f"/api/v1/deployments/{deployment['slug']}/query"

    # 5. Deploy v2 a production (v2 queda draft → debe rechazarse)
    bad = await async_client.post(
        "/api/v1/deployments",
        headers=headers,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v2["id"],
            "environment_id": prod["id"],
        },
    )
    assert bad.status_code == 409, bad.text

    # 6. Promover v2 (draft → ready → production) y desplegar
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v2['id']}/promote",
        headers=headers,
        json={"status": "ready"},
    )
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v2['id']}/promote",
        headers=headers,
        json={"status": "production"},
    )
    dep2 = await async_client.post(
        "/api/v1/deployments",
        headers=headers,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v2["id"],
            "environment_id": prod["id"],
        },
    )
    assert dep2.status_code == 201, dep2.text
    assert dep2.json()["agent_version_id"] == v2["id"]
    assert dep2.json()["slug"].startswith("inventory-assistant-production-")

    # 7. Rollback al último bueno (v1)
    rb = await async_client.post(
        f"/api/v1/deployments/{dep2.json()['id']}/rollback", headers=headers
    )
    assert rb.status_code == 200, rb.text
    rollback = rb.json()
    assert rollback["status"] == "healthy"
    assert rollback["agent_version_id"] == v1["id"]
    assert rollback["rollback_from_id"] == dep2.json()["id"]

    # 8. Listar deployments: 3 registros de historia
    listing = await async_client.get("/api/v1/deployments", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["count"] == 3


@pytest.mark.asyncio
async def test_deployments_are_tenant_isolated(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Isolation Org A")
    org_a["session"] = await _owner_session(org_a["organization_id"])
    org_b = await _create_org(async_client, "Isolation Org B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    headers_a, headers_b = _headers(org_a), _headers(org_b)

    agent = await _create_agent(async_client, headers_a, "Secret Agent")
    created = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions", headers=headers_a, json={}
    )
    v1 = created.json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v1['id']}/promote",
        headers=headers_a,
        json={"status": "ready"},
    )
    envs = (await async_client.get("/api/v1/environments", headers=headers_a)).json()
    prod = next(e for e in envs["environments"] if e["slug"] == "production")
    dep = await async_client.post(
        "/api/v1/deployments",
        headers=headers_a,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v1["id"],
            "environment_id": prod["id"],
        },
    )
    assert dep.status_code == 201, dep.text
    dep_id = dep.json()["id"]

    # Org B no puede ver ni tocar nada del org A (404, no 403: sin leak)
    for path in (
        f"/api/v1/deployments/{dep_id}",
        f"/api/v1/agents/{agent['id']}/versions/{v1['id']}",
    ):
        resp = await async_client.get(path, headers=headers_b)
        assert resp.status_code == 404, (path, resp.status_code, resp.text)

    rb = await async_client.post(
        f"/api/v1/deployments/{dep_id}/rollback", headers=headers_b
    )
    assert rb.status_code == 404

    # Org B no puede desplegar el agente de org A
    envs_b = (await async_client.get("/api/v1/environments", headers=headers_b)).json()
    prod_b = next(e for e in envs_b["environments"] if e["slug"] == "production")
    bad = await async_client.post(
        "/api/v1/deployments",
        headers=headers_b,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v1["id"],
            "environment_id": prod_b["id"],
        },
    )
    assert bad.status_code == 404


@pytest.mark.asyncio
async def test_deployments_require_permission(async_client: AsyncClient) -> None:
    """Una API key sin scopes de deployments recibe 403."""
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    org = await _create_org(async_client, "Perms Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    token = await billing.create_api_key(
        UUID(org["organization_id"]),
        name="read-only",
        scopes=["rag:read"],
        created_by=None,
    )
    limited_headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }

    resp = await async_client.get("/api/v1/deployments", headers=limited_headers)
    assert resp.status_code == 403, resp.text
    resp = await async_client.get("/api/v1/environments", headers=limited_headers)
    assert resp.status_code == 403, resp.text

    agent = await _create_agent(async_client, headers, "Perm Agent")
    created = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions", headers=headers, json={}
    )
    resp = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{created.json()['id']}/promote",
        headers=limited_headers,
        json={"status": "ready"},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_version_creation_requires_agents_version_permission(
    async_client: AsyncClient,
) -> None:
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    org = await _create_org(async_client, "Version Perms Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)
    agent = await _create_agent(async_client, headers, "VP Agent")

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    token = await billing.create_api_key(
        UUID(org["organization_id"]),
        name="reader",
        scopes=["rag:read"],
        created_by=None,
    )
    limited = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }
    resp = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions", headers=limited, json={}
    )
    assert resp.status_code == 403, resp.text

    # Lectura de versiones sí está permitida con agents:read… pero rag:read
    # no incluye agents:read: sigue 403 (sin leak de metadatos).
    resp = await async_client.get(
        f"/api/v1/agents/{agent['id']}/versions", headers=limited
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_rollback_requires_previous_version(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "NoRollback Org")
    org["session"] = await _owner_session(org["organization_id"])
    headers = _headers(org)

    agent = await _create_agent(async_client, headers, "Only Version")
    created = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions", headers=headers, json={}
    )
    v1 = created.json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v1['id']}/promote",
        headers=headers,
        json={"status": "ready"},
    )
    envs = (await async_client.get("/api/v1/environments", headers=headers)).json()
    prod = next(e for e in envs["environments"] if e["slug"] == "production")
    dep = await async_client.post(
        "/api/v1/deployments",
        headers=headers,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v1["id"],
            "environment_id": prod["id"],
        },
    )
    assert dep.status_code == 201

    rb = await async_client.post(
        f"/api/v1/deployments/{dep.json()['id']}/rollback", headers=headers
    )
    assert rb.status_code == 409, rb.text
    assert "previous version" in rb.json()["message"]

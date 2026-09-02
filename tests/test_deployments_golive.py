# =============================================================================
# Deployments Go Live (PROMPT 05) — eventos, permisos granulares, readiness
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
            "email": f"gl-{uuid4().hex[:8]}@example.com",
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


async def _setup_deployed_agent(client: AsyncClient, h: dict, name: str) -> tuple[dict, dict]:
    agent = (
        await client.post(
            "/api/v1/agents",
            headers=h,
            json={"name": name, "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await client.post(f"/api/v1/agents/{agent['id']}/versions", headers=h, json={})
    ).json()
    await client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=h,
        json={"status": "ready"},
    )
    envs = (await client.get("/api/v1/environments", headers=h)).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    deployment = await client.post(
        "/api/v1/deployments",
        headers=h,
        json={
            "agent_id": agent["id"],
            "agent_version_id": version["id"],
            "environment_id": prod["id"],
        },
    )
    assert deployment.status_code == 201, deployment.text
    return agent, deployment.json()


@pytest.mark.asyncio
async def test_deployment_events_recorded_and_listed(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Events Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    agent, deployment = await _setup_deployed_agent(async_client, h, "Events Agent")

    events = await async_client.get(
        f"/api/v1/deployments/{deployment['id']}/events", headers=h
    )
    assert events.status_code == 200, events.text
    body = events.json()
    assert body["count"] == 3  # created → deploying → healthy
    event_names = [e["event"] for e in body["events"]]
    assert event_names == ["created", "deploying", "healthy"]

    # Desplegar una v2 para poder hacer rollback (necesita versión previa).
    v2 = (
        await async_client.post(
            f"/api/v1/agents/{agent['id']}/versions", headers=h, json={}
        )
    ).json()
    await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{v2['id']}/promote",
        headers=h,
        json={"status": "ready"},
    )
    envs = (await async_client.get("/api/v1/environments", headers=h)).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    dep2 = await async_client.post(
        "/api/v1/deployments",
        headers=h,
        json={
            "agent_id": agent["id"],
            "agent_version_id": v2["id"],
            "environment_id": prod["id"],
        },
    )
    assert dep2.status_code == 201, dep2.text

    # Rollback agrega eventos (rolled_back + created + deploying + healthy + rolled_back_to).
    rb = await async_client.post(
        f"/api/v1/deployments/{dep2.json()['id']}/rollback", headers=h
    )
    assert rb.status_code == 200, rb.text
    new_deployment = rb.json()
    events2 = await async_client.get(
        f"/api/v1/deployments/{dep2.json()['id']}/events", headers=h
    )
    assert events2.json()["count"] == 4  # + rolled_back
    events3 = await async_client.get(
        f"/api/v1/deployments/{new_deployment['id']}/events", headers=h
    )
    names3 = [e["event"] for e in events3.json()["events"]]
    assert names3 == ["created", "deploying", "healthy", "rolled_back_to"]

    # Aislamiento cross-org.
    org_b = await _create_org(async_client, "Events B")
    org_b["session"] = await _owner_session(org_b["organization_id"])
    resp = await async_client.get(
        f"/api/v1/deployments/{deployment['id']}/events", headers=_headers(org_b)
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deploy_requires_granular_permission(async_client: AsyncClient) -> None:
    """Una key con rag:read no despliega; una con deployments:deploy sí."""
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    org = await _create_org(async_client, "Perms Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    agent, deployment = await _setup_deployed_agent(async_client, h, "Perms Agent")

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    rag_token = await billing.create_api_key(
        UUID(org["organization_id"]), name="rag", scopes=["rag:read"], created_by=None
    )
    limited = {
        "Authorization": f"Bearer {rag_token}",
        "X-Organization-Id": org["organization_id"],
    }
    resp = await async_client.post(
        "/api/v1/deployments",
        headers=limited,
        json={
            "agent_id": agent["id"],
            "agent_version_id": deployment["agent_version_id"],
            "environment_id": deployment["environment_id"],
        },
    )
    assert resp.status_code == 403, resp.text

    rollback_limited = await async_client.post(
        f"/api/v1/deployments/{deployment['id']}/rollback", headers=limited
    )
    assert rollback_limited.status_code == 403, rollback_limited.text

    # Los eventos (lectura) sí son accesibles con deployments:read… rag:read no
    # lo incluye → 403 (sin leak de historial).
    events = await async_client.get(
        f"/api/v1/deployments/{deployment['id']}/events", headers=limited
    )
    assert events.status_code == 403, events.text


@pytest.mark.asyncio
async def test_promote_to_production_requires_deployments_promote(
    async_client: AsyncClient,
) -> None:
    """Un miembro con agents:version promueve a ready pero no a production."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password
    from src.platform.auth.session import encrypt_session

    org = await _create_org(async_client, "Promote Perms")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    oid = UUID(org["organization_id"])

    agent = (
        await client_post_agent(async_client, h)
    ).json()
    version = (
        await async_client.post(
            f"/api/v1/agents/{agent['id']}/versions", headers=h, json={}
        )
    ).json()

    # Miembro con rol member (agents:version + deployments:read, sin promote).
    member_email = f"member-{uuid4().hex[:8]}@example.com"
    session = await get_async_session()
    try:
        member = (
            await session.execute(
                text(
                    "INSERT INTO users (id, organization_id, external_id, email_hash, "
                    "role, email, password_hash) "
                    "VALUES (gen_random_uuid(), :oid, :ext, :eh, 'member', "
                    ":email, :ph) RETURNING id"
                ),
                {
                    "oid": oid,
                    "ext": f"member-{uuid4().hex[:12]}",
                    "eh": __import__("hashlib").sha256(member_email.encode()).hexdigest(),
                    "email": member_email,
                    "ph": hash_password("secret-123"),
                },
            )
        ).fetchone()
        member_id = member.id
        await session.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role_id) "
                "SELECT :oid, :uid, id FROM roles "
                "WHERE organization_id IS NULL AND name = 'member' "
                "ON CONFLICT DO NOTHING"
            ),
            {"oid": oid, "uid": member_id},
        )
        await session.commit()
    finally:
        await session.close()

    member_headers = {
        "Authorization": f"Bearer {encrypt_session(member_id, oid)}",
        "X-Organization-Id": org["organization_id"],
    }

    # agents:version alcanza para draft→ready…
    ready = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=member_headers,
        json={"status": "ready"},
    )
    assert ready.status_code == 200, ready.text

    # …pero production exige deployments:promote (member no lo tiene).
    prod = await async_client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=member_headers,
        json={"status": "production"},
    )
    assert prod.status_code == 403, prod.text


async def client_post_agent(client: AsyncClient, h: dict):
    return await client.post(
        "/api/v1/agents",
        headers=h,
        json={"name": "Promote Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
    )


@pytest.mark.asyncio
async def test_readiness_includes_golive_items(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Readiness GoLive")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    agent = (await client_post_agent(async_client, h)).json()

    readiness = await async_client.get(
        f"/api/v1/agents/{agent['id']}/readiness", headers=h
    )
    assert readiness.status_code == 200, readiness.text
    items = {i["key"]: i for i in readiness.json()["items"]}
    assert "rate_limits" in items
    assert "observability" in items
    assert items["rate_limits"]["met"] is True
    assert items["observability"]["met"] is True
    # Los items informativos no pesan en el score.
    assert items["rate_limits"]["weight"] == 0

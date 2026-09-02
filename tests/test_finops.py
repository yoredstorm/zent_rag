# =============================================================================
# FinOps (PROMPT 07) — breakdown por dimensión, economics, alerts
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
            "email": f"fin-{uuid4().hex[:8]}@example.com",
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


async def _seed_usage(client: AsyncClient, org: dict, cost: float) -> None:
    """Inserta usage_events de prueba con agent/deployment atribuido."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    oid = UUID(org["organization_id"])
    agent = (
        await client.post(
            "/api/v1/agents",
            headers=_headers(org),
            json={"name": "Fin Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await client.post(f"/api/v1/agents/{agent['id']}/versions", headers=_headers(org), json={})
    ).json()
    await client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=_headers(org),
        json={"status": "ready"},
    )
    envs = (await client.get("/api/v1/environments", headers=_headers(org))).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    dep = (
        await client.post(
            "/api/v1/deployments",
            headers=_headers(org),
            json={
                "agent_id": agent["id"],
                "agent_version_id": version["id"],
                "environment_id": prod["id"],
            },
        )
    ).json()

    session = await get_async_session()
    try:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        for i in range(5):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, deployment_id, model, provider, total_tokens, "
                    "estimated_cost, status, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, :aid, :did, "
                    ":model, :provider, 1000, :cost, 'completed', :created)"
                ),
                {
                    "oid": oid,
                    "aid": UUID(agent["id"]),
                    "did": UUID(dep["id"]),
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "cost": cost,
                    "created": now - timedelta(hours=i),
                },
            )
        await session.commit()
    finally:
        await session.close()
    return agent, dep


@pytest.mark.asyncio
async def test_finops_breakdown_and_economics(async_client: AsyncClient) -> None:

    org = await _create_org(async_client, "FinOps Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    _agent, dep = await _seed_usage(async_client, org, 0.01)

    # Los endpoints /platform requieren sesión platform; usamos un admin platform.
    email = f"padmin-fin-{uuid4().hex[:8]}@zent.example"
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": __import__("hashlib").sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": __import__("src.platform.auth.passwords", fromlist=["hash_password"]).hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()

    login = await async_client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    plat = {"Authorization": f"Bearer {login.json()['access_token']}"}

    oid = org["organization_id"]
    breakdown = await async_client.get(
        f"/api/v1/platform/finops/breakdown?organization_id={oid}", headers=plat
    )
    assert breakdown.status_code == 200, breakdown.text
    body = breakdown.json()
    assert any(r["label"] == "Fin Agent" and r["cost"] > 0 for r in body["by_agent"])
    assert any(r["requests"] == 5 for r in body["by_agent"])
    assert any(r["label"] == dep["slug"] and r["cost"] > 0 for r in body["by_deployment"])
    assert any(r["label"] == "openai" for r in body["by_provider"])
    assert any(r["label"] == "gpt-4o-mini" for r in body["by_model"])
    assert any(r["requests"] == 5 for r in body["by_workspace"])  # sin workspace

    econ = await async_client.get(
        f"/api/v1/platform/finops/economics?organization_id={oid}", headers=plat
    )
    assert econ.status_code == 200, econ.text
    e = econ.json()
    assert e["requests"] == 5
    assert e["cost_per_request"] == pytest.approx(0.01)
    assert e["cost_per_1k_requests"] == pytest.approx(10.0)
    assert e["total_cost"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_finops_alerts_budget_and_ack(async_client: AsyncClient) -> None:

    org = await _create_org(async_client, "FinOps Alerts")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    oid = UUID(org["organization_id"])

    # Semilla de uso con costo alto (0.20 × 5 = $1.0).
    _agent, _dep = await _seed_usage(async_client, org, 0.20)

    # Platform admin.
    email = f"padmin-alert-{uuid4().hex[:8]}@zent.example"
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.auth.passwords import hash_password

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', :email, :ph, true)"
            ),
            {
                "ext": f"plat-{uuid4().hex[:12]}",
                "eh": __import__("hashlib").sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email},
        )
        await session.commit()
    finally:
        await session.close()

    login = await async_client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    plat = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Budget de $0.50 < costo $1.00 → alerta al ejecutar checks.
    budget = await async_client.put(
        f"/api/v1/platform/finops/organizations/{org['organization_id']}/budget",
        headers=plat,
        json={"budget_cents": 50},
    )
    assert budget.status_code == 200, budget.text

    check = await async_client.post(
        "/api/v1/platform/finops/check", headers=plat, json={"organization_id": org["organization_id"]}
    )
    assert check.status_code == 200, check.text
    check_dup = await async_client.post(
        "/api/v1/platform/finops/check", headers=plat, json={"organization_id": org["organization_id"]}
    )
    assert check_dup.status_code == 200, check_dup.text

    alerts = await async_client.get(
        f"/api/v1/platform/finops/alerts?organization_id={org['organization_id']}", headers=plat
    )
    assert alerts.status_code == 200, alerts.text
    body = alerts.json()
    types = [a["alert_type"] for a in body["alerts"]]
    assert "budget_exceeded" in types, types
    budget_alert = next(a for a in body["alerts"] if a["alert_type"] == "budget_exceeded")
    assert budget_alert["acknowledged"] is False

    # Reconocer.
    ack = await async_client.post(
        f"/api/v1/platform/finops/alerts/{budget_alert['id']}/ack?organization_id={org['organization_id']}",
        headers=plat,
    )
    assert ack.status_code == 200, ack.text
    alerts2 = await async_client.get(
        f"/api/v1/platform/finops/alerts?organization_id={org['organization_id']}", headers=plat
    )
    assert alerts2.json()["alerts"][0]["acknowledged"] is True

    # Dedupe 24h: los re-checks sin ack NO duplican la alerta.
    assert sum(1 for a in body["alerts"] if a["alert_type"] == "budget_exceeded") == 1
    # Tras ack, un nuevo check puede re-alertar (semántica de alertas).
    check2 = await async_client.post(
        "/api/v1/platform/finops/check", headers=plat, json={"organization_id": org["organization_id"]}
    )
    assert check2.status_code == 200
    alerts3 = await async_client.get(
        f"/api/v1/platform/finops/alerts?organization_id={org['organization_id']}", headers=plat
    )
    assert sum(1 for a in alerts3.json()["alerts"] if a["alert_type"] == "budget_exceeded") >= 1

# =============================================================================
# Observability (PROMPT 08) — system health, SLIs/SLOs, incident alerts
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"obs-{uuid4().hex[:8]}@example.com",
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


async def _deploy_agent(client: AsyncClient, org: dict, name: str) -> tuple[dict, dict]:
    agent = (
        await client.post(
            "/api/v1/agents",
            headers=_headers(org),
            json={"name": name, "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
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
    return agent, dep


async def _seed_usage(
    client: AsyncClient,
    org: dict,
    deployment_id: str,
    ok_count: int = 10,
    error_count: int = 2,
    latency_ms: float = 300.0,
) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    oid = UUID(org["organization_id"])
    did = UUID(deployment_id)
    session = await get_async_session()
    try:
        now = datetime.now(timezone.utc)
        for i in range(ok_count):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, deployment_id, model, provider, total_tokens, latency_ms, "
                    "status, estimated_cost, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, NULL, :did, "
                    ":model, 'openai', 500, :lat, 'completed', 0.001, :created)"
                ),
                {
                    "oid": oid,
                    "did": did,
                    "model": "gpt-4o-mini",
                    "lat": latency_ms,
                    "created": now - timedelta(minutes=i),
                },
            )
        for i in range(error_count):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, deployment_id, model, provider, total_tokens, latency_ms, "
                    "status, estimated_cost, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, NULL, :did, "
                    ":model, 'openai', 500, :lat, 'error', 0.001, :created)"
                ),
                {
                    "oid": oid,
                    "did": did,
                    "model": "gpt-4o-mini",
                    "lat": latency_ms,
                    "created": now - timedelta(minutes=i),
                },
            )
        await session.commit()
    finally:
        await session.close()


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib

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
                "eh": hashlib.sha256(email.encode()).hexdigest(),
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
    login = await client.post(
        "/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"}
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_system_health_endpoint(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-health-{uuid4().hex[:8]}@zent.example")
    resp = await async_client.get("/api/v1/platform/health", headers=plat)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = [c["name"] for c in body["checks"]]
    assert "database" in names and "redis" in names and "qdrant" in names
    db = next(c for c in body["checks"] if c["name"] == "database")
    assert db["status"] == "ok"
    assert body["status"] in ("ok", "degraded")


@pytest.mark.asyncio
async def test_deployment_slos_percentiles(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "SLO Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    _agent, dep = await _deploy_agent(async_client, org, "Slo Agent")
    await _seed_usage(
        async_client, org, dep["id"], ok_count=10, error_count=2, latency_ms=1000.0
    )

    plat = await _platform_admin(async_client, f"padmin-slo-{uuid4().hex[:8]}@zent.example")

    # Endpoint de plataforma.
    resp = await async_client.get(
        f"/api/v1/platform/deployments/{dep['id']}/slos", headers=plat
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == dep["slug"]
    win_1h = next(w for w in body["windows"] if w["window"] == "1h")
    assert win_1h["requests"] == 12
    assert win_1h["errors"] == 2
    assert win_1h["error_rate_pct"] == pytest.approx(16.67, abs=0.1)
    assert win_1h["availability_pct"] == pytest.approx(83.33, abs=0.1)
    assert win_1h["p50_ms"] == pytest.approx(1000.0, abs=1.0)
    assert win_1h["p95_ms"] == pytest.approx(1000.0, abs=1.0)
    assert win_1h["status"] == "failed"  # error rate 16.7% > 5%

    # Endpoint tenant.
    tenant = await async_client.get(
        f"/api/v1/deployments/{dep['id']}/slos", headers=h
    )
    assert tenant.status_code == 200, tenant.text
    assert tenant.json()["slug"] == dep["slug"]

    # Org SLOs agregadas.
    agg = await async_client.get(
        f"/api/v1/platform/organizations/{org['organization_id']}/slos", headers=plat
    )
    assert agg.status_code == 200, agg.text
    assert len(agg.json()["deployments"]) == 1
    assert agg.json()["aggregate_24h"]["requests"] == 12


@pytest.mark.asyncio
async def test_incident_alerts_and_webhook(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Incident Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    _agent, dep = await _deploy_agent(async_client, org, "Incident Agent")
    # 40 requests 24h con 6 errores → error rate 15% (>5%) y disponibilidad 85% (<99%).
    await _seed_usage(
        async_client, org, dep["id"], ok_count=34, error_count=6, latency_ms=1000.0
    )

    plat = await _platform_admin(
        async_client, f"padmin-incident-{uuid4().hex[:8]}@zent.example"
    )

    # Webhook configurado a una URL inválida → delivery falla (fail-soft).
    wb = await async_client.put(
        f"/api/v1/platform/organizations/{org['organization_id']}/ops-webhook",
        headers=plat,
        json={"url": "https://example.invalid/hook", "enabled": True},
    )
    assert wb.status_code == 200, wb.text

    # Check → alertas high_error_rate + low_availability.
    check = await async_client.post(
        "/api/v1/platform/obs/check",
        headers=plat,
        json={"organization_id": org["organization_id"]},
    )
    assert check.status_code == 200, check.text
    types = [a["alert_type"] for a in check.json()["alerts_created"]]
    assert "high_error_rate" in types, types
    assert "low_availability" in types, types
    assert "high_latency_p95" not in types  # p95=1000ms < 15000ms

    alerts = await async_client.get(
        f"/api/v1/platform/obs/alerts?organization_id={org['organization_id']}", headers=plat
    )
    assert alerts.status_code == 200, alerts.text
    body = alerts.json()
    assert body["count"] >= 2
    err_alert = next(a for a in body["alerts"] if a["alert_type"] == "high_error_rate")
    assert err_alert["status"] == "open"
    assert err_alert["webhook_status"] == "failed"  # URL inválida, fail-soft
    assert err_alert["deployment_id"] == dep["id"]

    # Dedupe: re-check no duplica.
    check2 = await async_client.post(
        "/api/v1/platform/obs/check",
        headers=plat,
        json={"organization_id": org["organization_id"]},
    )
    assert check2.status_code == 200
    assert check2.json()["count"] == 0

    # Resolver.
    resolve = await async_client.post(
        f"/api/v1/platform/obs/alerts/{err_alert['id']}/resolve", headers=plat
    )
    assert resolve.status_code == 200, resolve.text
    alerts2 = await async_client.get(
        f"/api/v1/platform/obs/alerts?organization_id={org['organization_id']}&status=resolved",
        headers=plat,
    )
    assert any(a["id"] == err_alert["id"] for a in alerts2.json()["alerts"])

    # Tenant ve sus propias alertas del deployment.
    tenant = await async_client.get(f"/api/v1/deployments/{dep['id']}/incidents", headers=h)
    assert tenant.status_code == 200, tenant.text
    assert any(a["deployment_id"] == dep["id"] for a in tenant.json()["alerts"])


@pytest.mark.asyncio
async def test_webhook_delivered_success(async_client: AsyncClient) -> None:
    """Con webhook válido (monkeypatch de _post_webhook) el estado es 'delivered'."""
    import src.platform.observability.alerts as alerts_mod

    org = await _create_org(async_client, "Webhook Org")
    org["session"] = await _owner_session(org["organization_id"])
    _agent, dep = await _deploy_agent(async_client, org, "Webhook Agent")
    await _seed_usage(async_client, org, dep["id"], ok_count=2, error_count=3)

    plat = await _platform_admin(
        async_client, f"padmin-webhook-{uuid4().hex[:8]}@zent.example"
    )

    async def _fake_post(url: str, payload: dict) -> bool:
        return True

    original = alerts_mod._post_webhook
    alerts_mod._post_webhook = _fake_post
    try:
        wb = await async_client.put(
            f"/api/v1/platform/organizations/{org['organization_id']}/ops-webhook",
            headers=plat,
            json={"url": "https://hooks.example.test/ops", "enabled": True},
        )
        assert wb.status_code == 200, wb.text
        check = await async_client.post(
            "/api/v1/platform/obs/check",
            headers=plat,
            json={"organization_id": org["organization_id"]},
        )
        assert check.status_code == 200, check.text
        created = check.json()["alerts_created"]
        assert created, "se esperaban alertas"
        assert all(a["webhook_status"] == "delivered" for a in created), created
    finally:
        alerts_mod._post_webhook = original

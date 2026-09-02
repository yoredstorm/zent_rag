# =============================================================================
# Real-Time Analytics & Streaming (PROMPT 19)
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
            "email": f"rt-{uuid4().hex[:8]}@example.com",
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


async def _platform_admin(client: AsyncClient, email: str) -> dict:
    import hashlib as hl

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
                "eh": hl.sha256(email.encode()).hexdigest(),
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


async def _seed_usage(client: AsyncClient, org: dict, n: int = 5, cost: float = 0.001) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        now = datetime.now(timezone.utc)
        for i in range(n):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "agent_id, model, provider, total_tokens, latency_ms, status, "
                    "estimated_cost, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, NULL, 'gpt-4o-mini', "
                    "'openai', 100, 150.0, 'completed', :cost, :created)"
                ),
                {"oid": UUID(org["organization_id"]), "cost": cost, "created": now - timedelta(minutes=i)},
            )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_live_summary_and_timeseries(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RT Summary Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-rt-{uuid4().hex[:8]}@zent.example")
    await _seed_usage(async_client, org, n=5, cost=0.001)

    summary = await async_client.get(
        "/api/v1/platform/realtime/summary?minutes=30", headers=plat
    )
    assert summary.status_code == 200, summary.text
    s = summary.json()
    assert s["requests"] >= 5
    assert isinstance(s["error_rate_pct"], float)
    assert s["active_organizations"] >= 1
    assert any(m["model"] == "gpt-4o-mini" for m in s["by_model"])

    ts = await async_client.get(
        "/api/v1/platform/realtime/timeseries?hours=24", headers=plat
    )
    assert ts.status_code == 200, ts.text
    points = ts.json()["points"]
    assert len(points) >= 1
    assert points[-1]["requests"] >= 5

    csv_resp = await async_client.get(
        "/api/v1/platform/realtime/timeseries?hours=24&format=csv", headers=plat
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert "bucket,requests" in csv_resp.json()["payload"]


@pytest.mark.asyncio
async def test_realtime_publish_and_consumer_spike(async_client: AsyncClient) -> None:
    from src.platform.realtime.stream import (
        _handle_spike,
        publish_event,
        set_auto_correction,
    )

    org = await _create_org(async_client, "RT Spike Org")
    org["session"] = await _owner_session(org["organization_id"])
    oid = UUID(org["organization_id"])
    deployment_id = uuid4()

    # Publicar 6 eventos de error para el mismo deployment (ventana 2 min).
    for _ in range(6):
        await publish_event(
            "api_query",
            {
                "organization_id": str(oid),
                "deployment_id": str(deployment_id),
                "status": 500,
                "latency_ms": 900.0,
                "tokens": 100,
                "cost": 0.001,
            },
        )

    # Consumidor detecta el spike (cooldown 2 min evita re-alertas en el mismo run).
    await _handle_spike(str(deployment_id), str(oid), 6)

    from src.platform.observability.alerts import list_alerts

    alerts = await list_alerts(oid, status=None, limit=10)
    types = [a["alert_type"] for a in alerts]
    assert "realtime_error_spike" in types

    # Cooldown: re-públicar + re-alerta no duplica (dedupe de incident_alerts).
    for _ in range(6):
        await publish_event(
            "api_query",
            {
                "organization_id": str(oid),
                "deployment_id": str(deployment_id),
                "status": "error",
                "latency_ms": 900.0,
                "tokens": 100,
                "cost": 0.001,
            },
        )
    await _handle_spike(str(deployment_id), str(oid), 6)
    alerts2 = await list_alerts(oid, status=None, limit=10)
    assert sum(1 for a in alerts2 if a["alert_type"] == "realtime_error_spike") == 1

    # Auto-corrección: flag on/off.
    set_auto_correction(True)
    from src.platform.realtime.stream import auto_correction_enabled

    assert auto_correction_enabled() is True
    set_auto_correction(False)
    assert auto_correction_enabled() is False


@pytest.mark.asyncio
async def test_sse_event_source_yields(async_client: AsyncClient) -> None:
    from src.platform.realtime.stream import event_source, publish_event

    org = await _create_org(async_client, "RT SSE Org")
    org["session"] = await _owner_session(org["organization_id"])
    oid = org["organization_id"]

    gen = event_source()
    it = gen.__aiter__()

    async def _next_frame():
        return await it.__anext__()

    import asyncio

    # Suscribirse primero (el primer next() suscribe) y publicar mientras espera.
    task = asyncio.create_task(_next_frame())
    await asyncio.sleep(0.2)
    await publish_event(
        "agent_run",
        {
            "organization_id": oid,
            "agent_id": str(uuid4()),
            "model": "gpt-4o-mini",
            "tokens": 50,
            "cost": 0.0005,
            "latency_ms": 100.0,
            "status": "completed",
        },
    )
    try:
        first = await asyncio.wait_for(task, timeout=10)
    except asyncio.TimeoutError:
        first = ""
    # Cerrar el generador.
    await gen.aclose()
    assert "event: agent_run" in first
    assert '"organization_id": "' in first


@pytest.mark.asyncio
async def test_auto_correction_endpoint(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RT AC Org")
    plat = await _platform_admin(async_client, f"padmin-rtac-{uuid4().hex[:8]}@zent.example")

    on = await async_client.post(
        "/api/v1/platform/realtime/auto-correction",
        headers=plat,
        json={"enabled": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["enabled"] is True
    status = await async_client.get("/api/v1/platform/realtime/auto-correction", headers=plat)
    assert status.json()["enabled"] is True
    off = await async_client.post(
        "/api/v1/platform/realtime/auto-correction",
        headers=plat,
        json={"enabled": False},
    )
    assert off.json()["enabled"] is False

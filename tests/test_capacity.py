# =============================================================================
# Capacity Planning & Auto-Scaling (PROMPT 22)
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
            "email": f"cap-{uuid4().hex[:8]}@example.com",
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


async def _seed_usage(client: AsyncClient, org: dict, n: int, cost: float = 0.001) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        now = datetime.now(timezone.utc)
        for i in range(n):
            await session.execute(
                text(
                    "INSERT INTO usage_events (request_id, event_type, organization_id, "
                    "model, provider, total_tokens, estimated_cost, status, created_at) "
                    "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', "
                    "'openai', 100, :cost, 'completed', :created)"
                ),
                {"oid": UUID(org["organization_id"]), "cost": cost, "created": now - timedelta(minutes=i)},
            )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_capacity_status_and_forecast(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-cap-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Bajar el límite del plan trial para que el uso sea relevante.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE plans SET requests_per_month = 100 WHERE is_trial = true")
        )
        await session.commit()
    finally:
        await session.close()

    await _seed_usage(async_client, org, n=30, cost=0.001)

    status = await async_client.get(
        f"/api/v1/platform/capacity/organizations/{oid}", headers=plat
    )
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["plan_limits"]["requests_per_month"] == 100
    assert body["usage"]["used_requests"] == 30
    assert body["utilization_pct"]["requests"] == pytest.approx(30.0, abs=0.5)
    assert body["soft_limit_exceeded"] is False
    assert body["hard_limit_exceeded"] is False
    assert body["days_until_limit"] is not None
    assert body["forecast_30d"]["requests"] >= 30


@pytest.mark.asyncio
async def test_capacity_soft_hard_limits(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Limits Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-capl-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE plans SET requests_per_month = 10 WHERE is_trial = true")
        )
        await session.commit()
    finally:
        await session.close()

    await _seed_usage(async_client, org, n=9, cost=0.001)  # 90% → soft

    status = await async_client.get(
        f"/api/v1/platform/capacity/organizations/{oid}", headers=plat
    )
    body = status.json()
    assert body["utilization_pct"]["requests"] == pytest.approx(90.0, abs=0.5)
    assert body["soft_limit_exceeded"] is True
    assert body["hard_limit_exceeded"] is False
    assert body["days_until_limit"] in (0, 1)  # 1 de margen con tasa diaria

    await _seed_usage(async_client, org, n=2, cost=0.001)  # 110% → hard
    status2 = await async_client.get(
        f"/api/v1/platform/capacity/organizations/{oid}", headers=plat
    )
    assert status2.json()["hard_limit_exceeded"] is True


@pytest.mark.asyncio
async def test_capacity_queues_and_scaling(async_client: AsyncClient) -> None:
    from src.platform.capacity.planning import (
        _scale_if_needed,
        auto_scale_enabled,
        queue_depths,
        record_scaling_event,
        set_auto_scale,
    )

    set_auto_scale(True)
    assert auto_scale_enabled() is True
    set_auto_scale(False)

    queues = await queue_depths()
    names = {q["queue"] for q in queues}
    assert "knowledge" in names
    assert "ingestion_pending" in names

    # Escalado manual registra evento.
    await record_scaling_event("knowledge", "manual_scale", depth=70, target=4, reason="test")
    from src.platform.capacity.planning import list_scaling_events

    events = await list_scaling_events(limit=10)
    assert any(e["queue"] == "knowledge" and e["action"] == "manual_scale" for e in events)

    # _scale_if_needed con profundidad alta → scale_up (cooldown por queue distinta).
    await _scale_if_needed("ingestion_pending", depth=100, current_workers=1)
    events2 = await list_scaling_events(limit=10)
    assert any(e["queue"] == "ingestion_pending" and e["action"] == "scale_up" for e in events2)


@pytest.mark.asyncio
async def test_capacity_simulate_and_summary(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Cap Sim Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-caps-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]
    await _seed_usage(async_client, org, n=10, cost=0.001)

    sim = await async_client.post(
        "/api/v1/platform/capacity/simulate",
        headers=plat,
        json={"organization_id": oid, "growth_pct": 100, "days": 30},
    )
    assert sim.status_code == 200, sim.text
    body = sim.json()
    assert body["current_requests"] == 10
    assert body["projected_requests"] == 20
    assert body["projected_cost"] == pytest.approx(0.02, abs=1e-4)
    assert body["cost_per_request"] == pytest.approx(0.001, abs=1e-6)

    summary = await async_client.get("/api/v1/platform/capacity/summary", headers=plat)
    assert summary.status_code == 200, summary.text
    s = summary.json()
    assert s["organizations_scanned"] >= 1
    assert "queues" in s and "scaling_events" in s

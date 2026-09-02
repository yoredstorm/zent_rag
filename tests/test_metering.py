# =============================================================================
# Usage Metering & Rate Limits v2 (PROMPT 26)
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
            "email": f"met-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"met-{uuid4().hex}",
    }


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


@pytest.mark.asyncio
async def test_metering_realtime_counters(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Meter Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-met-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.metering.metering import record

    await record(UUID(oid), tokens=500, cost=0.01, model="gpt-4o-mini")
    await record(UUID(oid), tokens=500, cost=0.01, model="gpt-4o-mini")
    await record(UUID(oid), tokens=100, cost=0.002, model="zent-cheap", status="error")

    rt = await async_client.get(
        f"/api/v1/platform/metering/realtime?organization_id={oid}", headers=plat
    )
    assert rt.status_code == 200, rt.text
    body = rt.json()
    entry = next(o for o in body["organizations"] if o["organization_id"] == oid)
    assert entry["requests"] == 3
    assert entry["tokens"] == 1100
    assert entry["cost"] == pytest.approx(0.022, abs=1e-3)
    assert entry["errors"] == 1
    assert entry["by_model"]["gpt-4o-mini"] == 2
    assert entry["by_model"]["zent-cheap"] == 1
    assert body["totals"]["requests"] >= 3


@pytest.mark.asyncio
async def test_metering_throttle_factor(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Throttle Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-thr-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.metering.metering import record

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE plans SET requests_per_month = 30 WHERE is_trial = true")
        )
        await session.commit()
    finally:
        await session.close()

    for _ in range(30):  # 30 de 1 diario → 3000%
        await record(UUID(oid), tokens=10, cost=0.0001)

    try:
        thr = await async_client.get(
            f"/api/v1/platform/metering/throttle?organization_id={oid}", headers=plat
        )
        assert thr.status_code == 200, thr.text
        t = thr.json()
        assert t["throttled"] is True
        assert t["throttle_factor"] < 1.0
        assert t["throttle_factor"] >= 0.2
        assert t["usage_pct"] > 100
    finally:
        session = await get_async_session()
        try:
            await session.execute(
                text("UPDATE plans SET requests_per_month = 500 WHERE is_trial = true")
            )
            await session.commit()
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_rate_limit_rules_and_effective(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Rules Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-rl-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    rules = await async_client.get("/api/v1/platform/rate-limits/rules", headers=plat)
    assert rules.status_code == 200, rules.text
    seeded = rules.json()["rules"]
    assert len(seeded) >= 6
    for stale in seeded:
        if stale["plan_name"] == "trial" and stale["endpoint_prefix"] == "/api/v1/rag/query":
            await async_client.delete(f"/api/v1/platform/rate-limits/rules/{stale['id']}", headers=plat)
    trial = next(r for r in seeded if r["plan_name"] == "trial" and r["endpoint_prefix"] == "/")
    assert trial["limit_per_minute"] == 30
    assert trial["burst"] == 10

    # Límites efectivos para la org trial.
    eff = await async_client.get(
        f"/api/v1/platform/rate-limits/rules/effective?organization_id={oid}&path=/api/v1/rag/query",
        headers=plat,
    )
    assert eff.status_code == 200, eff.text
    e = eff.json()
    assert e["plan_name"] == "trial"
    # El prefijo específico global (60/15) gana sobre el default trial (30/10) por longitud.
    assert e["rule"]["limit_per_minute"] == 60
    assert e["rule"]["burst"] == 15

    # Crear regla.
    created = await async_client.post(
        "/api/v1/platform/rate-limits/rules",
        headers=plat,
        json={"plan_name": "trial", "endpoint_prefix": "/api/v1/rag/query", "limit_per_minute": 5, "burst": 2},
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    eff2 = await async_client.get(
        f"/api/v1/platform/rate-limits/rules/effective?organization_id={oid}&path=/api/v1/rag/query",
        headers=plat,
    )
    assert eff2.json()["rule"]["limit_per_minute"] == 5
    assert eff2.json()["rule"]["burst"] == 2

    # Toggle + delete.
    toggled = await async_client.put(
        f"/api/v1/platform/rate-limits/rules/{rule_id}",
        headers=plat,
        json={"plan_name": "trial", "endpoint_prefix": "/api/v1/rag/query", "limit_per_minute": 5, "burst": 2, "enabled": False},
    )
    assert toggled.status_code == 200, toggled.text
    deleted = await async_client.delete(f"/api/v1/platform/rate-limits/rules/{rule_id}", headers=plat)
    assert deleted.status_code == 200, deleted.text


@pytest.mark.asyncio
async def test_plan_rate_limit_enforced_429(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "RL Enforce Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-rle-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Regla estricta para trial en /api/v1/agents: 2/min + 0 burst.
    created = await async_client.post(
        "/api/v1/platform/rate-limits/rules",
        headers=plat,
        json={"plan_name": "trial", "endpoint_prefix": "/api/v1/agents", "limit_per_minute": 2, "burst": 0},
    )
    assert created.status_code == 201, created.text

    from src.infrastructure.redis.cache import _get_redis

    # Limpiar el contador del minuto actual para el org+rule.
    client = await _get_redis()
    keys = await client.keys(f"rag:rl:{org['organization_id']}:*")
    for k in keys:
        await client.delete(k)

    h = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    for i in range(3):
        resp = await async_client.get("/api/v1/agents", headers=h)
        if i < 2:
            assert resp.status_code == 200, resp.text
        else:
            assert resp.status_code == 429, resp.text
            assert resp.json()["error_code"] == "rate_limit_plan_exceeded"

    # Delete la regla para no afectar otros tests de la org trial.
    deleted = await async_client.delete(f"/api/v1/platform/rate-limits/rules/{created.json()['id']}", headers=plat)
    assert deleted.status_code == 200

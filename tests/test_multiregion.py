# =============================================================================
# Multi-Region & Edge Caching (PROMPT 28)
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


def test_edge_cache_key_changes_with_policy_generation() -> None:
    from src.platform.edge.multiregion import cache_key

    oid, did, vid = uuid4(), uuid4(), uuid4()
    assert cache_key(oid, did, vid, "quién") != cache_key(
        oid, did, vid, "quién", generation="1"
    )


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"mr-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"mr-{uuid4().hex}",
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
async def test_organizations_primary_region_id_column_exists() -> None:
    """create_organization INSERT includes primary_region_id; CI schema must have it."""
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        found = (
            await session.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'organizations' "
                    "AND column_name = 'primary_region_id'"
                )
            )
        ).scalar()
        us_east = (
            await session.execute(
                text("SELECT 1 FROM regions WHERE code = 'us-east-1'")
            )
        ).scalar()
    finally:
        await session.close()
    assert found == 1
    assert us_east == 1


@pytest.mark.asyncio
async def test_regions_catalog_and_healthcheck(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-mr-{uuid4().hex[:8]}@zent.example")

    regions = await async_client.get("/api/v1/platform/regions", headers=plat)
    assert regions.status_code == 200, regions.text
    codes = [r["code"] for r in regions.json()["regions"]]
    assert {"us-east-1", "eu-west-1", "ap-southeast-1", "sa-east-1"} <= set(codes)
    us = next(r for r in regions.json()["regions"] if r["code"] == "us-east-1")
    assert us["replicas"][0]["kind"] == "postgres"
    assert us["replicas"][0]["healthy"] is True

    hc = await async_client.post("/api/v1/platform/regions/healthcheck", headers=plat)
    assert hc.status_code == 200, hc.text
    assert hc.json()["us-east-1"]["healthy"] is True
    assert hc.json()["us-east-1"]["latency_ms"] > 0


@pytest.mark.asyncio
async def test_region_resolve_and_failover(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MR Org")
    plat = await _platform_admin(async_client, f"padmin-mrf-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    resolved = await async_client.get(
        f"/api/v1/platform/regions/resolve?organization_id={oid}", headers=plat
    )
    assert resolved.status_code == 200, resolved.text
    r = resolved.json()
    assert r["region"] == "us-east-1"
    assert r["failed_over"] is False
    assert r["source"] == "primary"

    # Simular failover: marcar us-east-1 unhealthy → resolución cae a eu-west-1.
    sim = await async_client.post(
        f"/api/v1/platform/regions/us-east-1/failover?organization_id={oid}", headers=plat
    )
    assert sim.status_code == 200, sim.text
    assert sim.json()["simulated_unhealthy"] == "us-east-1"
    assert sim.json()["resolution"]["region"] == "eu-west-1"
    assert sim.json()["resolution"]["failed_over"] is True

    # Restaurar y verificar que la resolución vuelve a primary.
    from src.platform.edge.multiregion import set_region_health

    await set_region_health("us-east-1", True)
    resolved2 = await async_client.get(
        f"/api/v1/platform/regions/resolve?organization_id={oid}", headers=plat
    )
    assert resolved2.json()["region"] == "us-east-1"


@pytest.mark.asyncio
async def test_latency_by_region(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MR Lat Org")
    plat = await _platform_admin(async_client, f"padmin-mrl-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from src.platform.proxy.inference_proxy import log_inference

    R1 = f"tst-{uuid4().hex[:6]}-a"
    R2 = f"tst-{uuid4().hex[:6]}-b"
    for region, lat in [(R1, 80.0), (R1, 120.0), (R2, 200.0)]:
        await log_inference(
            organization_id=UUID(oid),
            deployment_id=None,
            agent_id=None,
            model="zent-fast",
            backend="tgi",
            status="completed",
            prompt_tokens=50,
            completion_tokens=25,
            latency_ms=lat,
            cost=0.001,
            region=region,
        )

    lat = await async_client.get("/api/v1/platform/regions/latency?hours=24", headers=plat)
    assert lat.status_code == 200, lat.text
    rows = {r["region"]: r for r in lat.json()["regions"]}
    assert rows[R1]["requests"] == 2
    assert rows[R1]["avg_latency_ms"] == pytest.approx(100.0, abs=0.1)
    assert rows[R1]["p95_latency_ms"] == pytest.approx(118.0, abs=0.5)
    assert rows[R2]["requests"] == 1


@pytest.mark.asyncio
async def test_edge_cache_hit_miss_and_bypass(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Edge Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-ed-{uuid4().hex[:8]}@zent.example")

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"mr-a-{uuid4().hex}"},
            json={"name": "Edge Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        version_id = (
            await session.execute(
                text(
                    "INSERT INTO agent_versions (id, agent_id, organization_id, "
                    "version_number, status, config_snapshot) "
                    "VALUES (gen_random_uuid(), :a, :o, 1, 'ready', '{}') "
                    "RETURNING id"
                ),
                {"a": UUID(agent["id"]), "o": UUID(org["organization_id"])},
            )
        ).scalar()
        env = (
            await session.execute(
                text(
                    "INSERT INTO environments (id, organization_id, name, slug, is_default) "
                    "VALUES (gen_random_uuid(), :o, 'production', 'prod-edge', true) "
                    "RETURNING id"
                ),
                {"o": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO deployments (id, agent_id, agent_version_id, organization_id, "
                "environment_id, slug, status) "
                "VALUES (gen_random_uuid(), :a, :v, :o, :e, 'edge-prod', 'healthy')"
            ),
            {
                "a": UUID(agent["id"]),
                "v": version_id,
                "o": UUID(org["organization_id"]),
                "e": env,
            },
        )
        await session.commit()
    finally:
        await session.close()

    from src.agents.runtime.agent_runtime import AgentRunResult
    from src.api.deps import get_agent_runtime
    from src.api.main import app

    class _Fake:
        def __init__(self):
            self.calls = 0

        async def run(self, request):
            self.calls += 1
            return AgentRunResult(
                run_id=uuid4(),
                agent_id=request.agent.id,
                organization_id=request.agent.organization_id,
                status="completed",
                answer=f"respuesta-cacheada-{self.calls}",
                message=request.message,
                total_latency_ms=50.0,
                total_tokens=30,
                cost=0.0001,
            )

    fake = _Fake()
    app.dependency_overrides[get_agent_runtime] = lambda: fake
    h = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
    }
    # Sin API key pública usamos la sesión portal para simular el ctx.

    q1 = await async_client.post(
        "/api/v1/deployments/edge-prod/query",
        headers={**_headers(org), "Idempotency-Key": f"mr-q-{uuid4().hex}"},
        json={"input": "pregunta cacheable"},
    )
    assert q1.status_code == 200, q1.text
    assert q1.headers.get("x-zent-cache") == "MISS"
    answer1 = q1.json()["answer"]
    assert "cacheada-1" in answer1

    q2 = await async_client.post(
        "/api/v1/deployments/edge-prod/query",
        headers={**_headers(org), "Idempotency-Key": f"mr-q-{uuid4().hex}"},
        json={"input": "pregunta cacheable"},
    )
    assert q2.status_code == 200, q2.text
    assert q2.headers.get("x-zent-cache") == "HIT"
    assert q2.json()["answer"] == answer1
    assert fake.calls == 1  # el runtime no se volvió a ejecutar

    # Bypass: ?cache=false fuerza nuevo run.
    q3 = await async_client.post(
        "/api/v1/deployments/edge-prod/query?cache=false",
        headers={**_headers(org), "Idempotency-Key": f"mr-q-{uuid4().hex}"},
        json={"input": "pregunta cacheable"},
    )
    assert q3.status_code == 200, q3.text
    assert q3.headers.get("x-zent-cache") == "BYPASS"
    assert fake.calls == 2

    stats = await async_client.get("/api/v1/platform/edge/cache/stats", headers=plat)
    assert stats.status_code == 200, stats.text
    assert stats.json()["hits"] >= 1
    assert stats.json()["misses"] >= 2
    assert stats.json()["hit_ratio"] > 0

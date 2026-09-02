# =============================================================================
# Multitenant LLM Proxy (PROMPT 27)
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
            "email": f"px-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"px-{uuid4().hex}",
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
async def test_proxy_models_catalog_and_upsert(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-px-{uuid4().hex[:8]}@zent.example")

    models = await async_client.get("/api/v1/platform/proxy/models", headers=plat)
    assert models.status_code == 200, models.text
    names = {m["model_name"] for m in models.json()["models"]}
    assert {"gpt-4o-mini", "zent-cheap", "zent-fast", "gpt-4o"} <= names

    created = await async_client.post(
        "/api/v1/platform/proxy/models",
        headers=plat,
        json={"model_name": "zent-xl", "backend": "vllm", "capacity": 25},
    )
    assert created.status_code == 201, created.text
    assert created.json()["capacity"] == 25
    assert created.json()["backend"] == "vllm"

    updated = await async_client.post(
        "/api/v1/platform/proxy/models",
        headers=plat,
        json={"model_name": "zent-xl", "backend": "tgi", "capacity": 60, "status": "active"},
    )
    assert updated.status_code == 201, updated.text
    assert updated.json()["capacity"] == 60
    assert updated.json()["backend"] == "tgi"


@pytest.mark.asyncio
async def test_proxy_queue_capacity_and_estimate(async_client: AsyncClient) -> None:
    from src.platform.proxy.inference_proxy import (
        admit,
        dequeue,
        enqueue,
        estimate_wait_ms,
        inflight,
        queue_snapshot,
        release_slot,
    )

    # Admisión normal (capacidad default 50 para modelo inexistente).
    first = await admit("pro", "zent-test-1")
    assert first["admitted"] is True
    assert first["capacity"] == 50

    # Ocupar capacidad: modelo con capacidad 1.
    await enqueue("trial", "zent-cap1")
    depth = await estimate_wait_ms("trial", "zent-cap1")
    assert depth > 0

    snap = await queue_snapshot()
    assert any(q["model"] == "zent-cap1" and q["plan"] == "trial" for q in snap["queues"])

    # Limpieza.
    await dequeue("trial", "zent-cap1")
    await release_slot("zent-test-1")
    assert await inflight("zent-test-1") == 0


@pytest.mark.asyncio
async def test_proxy_logs_and_performance(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Proxy Perf Org")
    plat = await _platform_admin(async_client, f"padmin-pxp-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]
    MODEL_NAME = f"zent-perf-{uuid4().hex[:6]}"

    from src.platform.proxy.inference_proxy import log_inference

    for i in range(5):
        await log_inference(
            organization_id=UUID(oid),
            deployment_id=None,
            agent_id=None,
            model=MODEL_NAME,
            backend="tgi",
            status="completed",
            prompt_tokens=100 + i * 10,
            completion_tokens=50,
            latency_ms=120.0 + i * 30,
            queue_wait_ms=5.0,
            cost=0.001,
        )
    await log_inference(
        organization_id=UUID(oid),
        deployment_id=None,
        agent_id=None,
        model=MODEL_NAME,
        backend="tgi",
        status="error",
        prompt_tokens=80,
        completion_tokens=0,
        latency_ms=3000.0,
        cost=0.0,
    )

    logs = await async_client.get(
        f"/api/v1/platform/proxy/inference-logs?organization_id={oid}&hours=24",
        headers=plat,
    )
    assert logs.status_code == 200, logs.text
    assert logs.json()["count"] == 6
    assert all(item["model"] == MODEL_NAME for item in logs.json()["logs"])

    perf = await async_client.get(
        f"/api/v1/platform/proxy/performance?model={MODEL_NAME}&hours=24", headers=plat
    )
    assert perf.status_code == 200, perf.text
    p = next(m for m in perf.json()["models"] if m["model"] == MODEL_NAME)
    assert p["requests"] == 6
    assert p["errors"] == 1
    assert p["avg_latency_ms"] == pytest.approx((120 + 150 + 180 + 210 + 240 + 3000) / 6, abs=1)
    assert p["p95_latency_ms"] == 2310.0  # percentile_cont(0.95) de 6 valores
    assert p["throughput_per_min"] == pytest.approx(6 / 1440, abs=0.01)
    assert p["backend"] == "tgi"


@pytest.mark.asyncio
async def test_deployment_rate_limit_and_runtime_guard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Proxy RL Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-pxrl-{uuid4().hex[:8]}@zent.example")

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"px-a-{uuid4().hex}"},
            json={"name": "Px Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    # Deployment + regla estricta (1/min) vía API real.
    env = await async_client.post(
        "/api/v1/environments",
        headers={**_headers(org), "Idempotency-Key": f"px-e-{uuid4().hex}"},
        json={"name": "production", "slug": "prod-px"},
    )
    assert env.status_code == 201, env.text
    session = await get_async_session()
    try:
        version = (
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
        await session.commit()
    finally:
        await session.close()
    dep = await async_client.post(
        "/api/v1/deployments",
        headers={**_headers(org), "Idempotency-Key": f"px-d-{uuid4().hex}"},
        json={"agent_id": agent["id"], "agent_version_id": str(version), "environment_slug": "prod-px"},
    )
    assert dep.status_code == 201, dep.text
    dep_id = UUID(dep.json()["id"])
    dep_slug = dep.json()["slug"]

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO rate_limit_rules (id, deployment_id, endpoint_prefix, "
                "limit_per_minute, burst, priority) "
                "VALUES (gen_random_uuid(), :d, '/agents/execute', 1, 0, 50)"
            ),
            {"d": dep_id},
        )
        await session.commit()
    finally:
        await session.close()

    from src.infrastructure.redis.cache import _get_redis

    client = await _get_redis()
    keys = await client.keys(f"rag:rl:dep:{dep_id}:*")
    for k in keys:
        await client.delete(k)

    # Ejecutar 3 runs con runtime real (loop parcheado) → 1 aceptado, 2 rechazados.
    from src.agents.runtime.agent_runtime import AgentRuntime
    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from src.infrastructure.llm.provider import LiteLLMProvider

    real_runtime = AgentRuntime(llm_provider=LiteLLMProvider())

    async def fake_loop(request, ctx, config, result):
        result.status = "completed"
        result.answer = "ok"
        result.total_tokens = 30
        result.cost = 0.0001

    real_runtime._run_loop = fake_loop  # type: ignore[method-assign]
    app.dependency_overrides[get_agent_runtime] = lambda: real_runtime
    run = await async_client.post(
        f"/api/v1/deployments/{dep_slug}/query",
        headers={**_headers(org), "Idempotency-Key": f"px-r-{uuid4().hex}"},
        json={"input": "hola"},
    )
    assert run.status_code == 200, run.text
    for _ in range(2):
        r2 = await async_client.post(
            f"/api/v1/deployments/{dep_slug}/query",
            headers={**_headers(org), "Idempotency-Key": f"px-r-{uuid4().hex}"},
            json={"input": "hola de nuevo"},
        )
        assert r2.status_code == 200, r2.text
        if r2.json().get("answer") == "":
            break
    assert r2.json()["answer"] == ""

    # Limpieza de la regla y deployment.
    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM rate_limit_rules WHERE deployment_id = :d"), {"d": dep_id}
        )
        await session.commit()
    finally:
        await session.close()

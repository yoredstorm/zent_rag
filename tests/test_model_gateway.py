# =============================================================================
# Model Gateway (PROMPT 18) — routes, A/B, budgets, fallback, analytics
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
            "email": f"gw-{uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_model_routes_ab_and_resolve(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GW Routes Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gw-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # A/B: 50/50 entre gpt-4o-mini y zent-cheap, más fallback default.
    r1 = await async_client.post(
        "/api/v1/platform/model-gateway/routes",
        headers=plat,
        json={
            "organization_id": oid, "name": "A", "condition_type": "default",
            "model": "gpt-4o-mini", "traffic_pct": 50, "priority": 0,
        },
    )
    assert r1.status_code == 201, r1.text
    r2 = await async_client.post(
        "/api/v1/platform/model-gateway/routes",
        headers=plat,
        json={
            "organization_id": oid, "name": "B", "condition_type": "latency",
            "condition_value": 1500, "model": "zent-cheap", "traffic_pct": 50, "priority": 1,
        },
    )
    assert r2.status_code == 201, r2.text

    listed = await async_client.get(
        f"/api/v1/platform/model-gateway/routes?organization_id={oid}", headers=plat
    )
    assert listed.json()["count"] == 2

    # Resolución: ambas rutas en candidatos, primario es uno de los dos.
    from src.platform.model_gateway.gateway import resolve_models

    candidates = await resolve_models(UUID(oid))
    assert candidates[0] in ("gpt-4o-mini", "zent-cheap")
    assert set(candidates[:2]) == {"gpt-4o-mini", "zent-cheap"}

    # Sin rutas → default.
    from src.core.config import get_settings

    other = await _create_org(async_client, "GW NoRoutes")
    no_routes = await resolve_models(UUID(other["organization_id"]))
    assert no_routes == [get_settings().LITELLM_DEFAULT_MODEL]

    # Toggle activación.
    toggled = await async_client.put(
        f"/api/v1/platform/model-gateway/routes/{r2.json()['id']}",
        headers=plat,
        json={
            "organization_id": oid, "name": "B", "condition_type": "latency",
            "condition_value": 1500, "model": "zent-cheap", "traffic_pct": 50,
            "priority": 1, "active": False,
        },
    )
    assert toggled.status_code == 200, toggled.text
    candidates2 = await resolve_models(UUID(oid))
    assert candidates2[0] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_model_budgets_blocking(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GW Budget Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gwb-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Ruta principal gpt-4o-mini + presupuesto de $0.01.
    await async_client.post(
        "/api/v1/platform/model-gateway/routes",
        headers=plat,
        json={
            "organization_id": oid, "name": "main", "condition_type": "default",
            "model": "gpt-4o-mini", "traffic_pct": 100, "priority": 0,
        },
    )
    budget = await async_client.post(
        "/api/v1/platform/model-gateway/budgets",
        headers=plat,
        json={"organization_id": oid, "model": "gpt-4o-mini", "monthly_budget_cents": 1},
    )
    assert budget.status_code == 201, budget.text

    # Sin gasto → no bloqueado; resuelve gpt-4o-mini.
    from src.platform.model_gateway.gateway import resolve_models

    candidates = await resolve_models(UUID(oid))
    assert candidates[0] == "gpt-4o-mini"

    # Gastar $0.02 en gpt-4o-mini (mes actual) → bloqueado → router cae a default.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, provider, total_tokens, estimated_cost, status, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'openai', "
                "100, 0.02, 'completed', NOW())"
            ),
            {"oid": UUID(oid)},
        )
        await session.commit()
    finally:
        await session.close()

    budgets = await async_client.get(
        f"/api/v1/platform/model-gateway/budgets?organization_id={oid}", headers=plat
    )
    assert budgets.status_code == 200, budgets.text
    b = budgets.json()["budgets"][0]
    assert b["blocked"] is True
    assert b["spent_cents"] >= 2.0

    candidates2 = await resolve_models(UUID(oid))
    assert "gpt-4o-mini" not in candidates2[:1]
    from src.core.config import get_settings

    assert candidates2[0] == get_settings().LITELLM_DEFAULT_MODEL


@pytest.mark.asyncio
async def test_gateway_analytics_and_fallback_flag(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "GW Analytics Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gwa-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from datetime import datetime, timezone

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        now = datetime.now(timezone.utc)
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, provider, total_tokens, latency_ms, status, estimated_cost, "
                "routing, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'openai', "
                "500, 300.0, 'completed', 0.001, :routing, :created)"
            ),
            {
                "oid": UUID(oid),
                "routing": '{"attempts": ["gpt-4o-mini", "zent-cheap"], "final": "zent-cheap"}',
                "created": now,
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, provider, total_tokens, latency_ms, status, estimated_cost, "
                "routing, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'zent-cheap', 'openai', "
                "400, 500.0, 'completed', 0.0005, NULL, :created)"
            ),
            {"oid": UUID(oid), "created": now},
        )
        await session.commit()
    finally:
        await session.close()

    analytics = await async_client.get(
        f"/api/v1/platform/model-gateway/analytics?organization_id={oid}", headers=plat
    )
    assert analytics.status_code == 200, analytics.text
    models = {m["model"]: m for m in analytics.json()["models"]}
    assert "gpt-4o-mini" in models
    assert models["gpt-4o-mini"]["requests"] == 1
    assert models["gpt-4o-mini"]["fallbacks"] == 1  # routing con 2 intentos
    assert models["zent-cheap"]["requests"] == 1
    assert models["zent-cheap"]["fallbacks"] == 0


@pytest.mark.asyncio
async def test_runtime_router_fallback(async_client: AsyncClient) -> None:
    """El runtime con zent-routed usa fallback cuando el primario falla."""
    from src.agents.runtime.agent_runtime import AgentRunRequest

    org = await _create_org(async_client, "GW Runtime Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gwr-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Ruta: primario que falla; el fallback es el default del gateway.
    await async_client.post(
        "/api/v1/platform/model-gateway/routes",
        headers=plat,
        json={
            "organization_id": oid, "name": "broken", "condition_type": "default",
            "model": "modelo-que-falla", "traffic_pct": 100, "priority": 0,
        },
    )

    # Runtime con LLM fake: falla en el primario, responde en el fallback (default).
    from src.core.config import get_settings

    default_model = get_settings().LITELLM_DEFAULT_MODEL

    class _FakeLLM:
        async def generate(self, prompt: str, model: str, max_tokens: int, temperature: float):
            if model == "modelo-que-falla":
                raise RuntimeError("provider down")
            from types import SimpleNamespace

            return SimpleNamespace(content='{"answer": "ok"}', prompt_tokens=10, completion_tokens=5, total_tokens=15)

    class _FakeToolContext:
        pass

    from src.core.domain.entities import Agent

    agent = Agent(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        organization_id=UUID(oid),
        name="Router Agent",
        model="zent-routed",
        system_prompt="t",
        config_json={},
    )
    runtime = _make_runtime(_FakeLLM())
    result = await runtime.run(
        AgentRunRequest(
            agent=agent,
            message="hola",
            permissions=frozenset(),
            org_config={},
        )
    )
    assert result.status == "completed"
    assert "router_fallback" in [s.get("type") for s in result.steps]
    fallback_step = next(s for s in result.steps if s.get("type") == "router_fallback")
    assert fallback_step["attempts"] == ["modelo-que-falla", default_model]
    assert fallback_step["final_model"] == default_model


def _make_runtime(llm):
    from src.agents.runtime.agent_runtime import AgentRuntime
    from src.infrastructure.redis.cache import RedisCache

    return AgentRuntime(llm_provider=llm, cache_provider=RedisCache())

# =============================================================================
# AI Model Budgets & Guardrails v2 (PROMPT 31)
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
            "email": f"mh-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(client: AsyncClient, organization_id: str) -> str:
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
        "Idempotency-Key": f"mh-{uuid4().hex}",
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
async def test_output_guardrails_crud_and_apply(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MH GR Org")
    plat = await _platform_admin(async_client, f"padmin-mhg-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={
            "organization_id": oid,
            "name": "Sin groserías",
            "kind": "toxicity",
            "action": "mask",
            "config": {"words": ["malapalabra"]},
        },
    )
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    bad_kind = await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={"organization_id": oid, "name": "x", "kind": "nope", "action": "mask", "config": {}},
    )
    assert bad_kind.status_code == 400

    # Aplicación.
    from src.platform.modelhealth.guardrails import protect_answer

    answer, violations, blocked = await protect_answer(UUID(oid), "hola malapalabra mundo")
    assert "malapalabra" not in answer
    assert "[REDACTED]" in answer
    assert violations[0]["kind"] == "toxicity"
    assert blocked is False

    # Block.
    await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={
            "organization_id": oid,
            "name": "Prohibido",
            "kind": "banned_topics",
            "action": "block",
            "config": {"words": ["hackear"]},
        },
    )
    answer2, violations2, blocked2 = await protect_answer(UUID(oid), "cómo hackear un sistema")
    assert blocked2 is True
    assert answer2 == ""

    # Toggle off.
    toggled = await async_client.post(
        f"/api/v1/platform/model-health/guardrails/{gid}/toggle",
        headers=plat,
        json={"enabled": False},
    )
    assert toggled.status_code == 200, toggled.text
    answer3, violations3, _ = await protect_answer(UUID(oid), "hola malapalabra mundo")
    assert "malapalabra" in answer3  # guardrail desactivado
    assert violations3 == []

    listed = await async_client.get(
        f"/api/v1/platform/model-health/guardrails?organization_id={oid}", headers=plat
    )
    assert listed.json()["guardrails"][0]["enabled"] is False


@pytest.mark.asyncio
async def test_output_guardrails_pii_and_length(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MH GR2 Org")
    plat = await _platform_admin(async_client, f"padmin-mhg2-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={
            "organization_id": oid,
            "name": "PII",
            "kind": "pii",
            "action": "mask",
            "config": {},
        },
    )
    await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={
            "organization_id": oid,
            "name": "Máx 20",
            "kind": "length_limit",
            "action": "warn",
            "config": {"max_chars": 20},
        },
    )
    await async_client.post(
        "/api/v1/platform/model-health/guardrails",
        headers=plat,
        json={
            "organization_id": oid,
            "name": "Regex",
            "kind": "custom_pattern",
            "action": "block",
            "config": {"patterns": ["tarjeta-\\d{4}"]},
        },
    )

    from src.platform.modelhealth.guardrails import protect_answer

    answer, violations, blocked = await protect_answer(
        UUID(oid), "mi correo es juan@example.com y el código es tarjeta-1234"
    )
    assert blocked is True  # regex block
    assert any(v["kind"] == "pii" for v in violations)
    assert any(v["kind"] == "custom_pattern" for v in violations)
    assert any(v["kind"] == "length_limit" for v in violations)


@pytest.mark.asyncio
async def test_model_budget_throttling(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "MH Budget Org")
    plat = await _platform_admin(async_client, f"padmin-mhb-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.modelhealth.guardrails import model_budget_status

    # Budget $0.10/mes para gpt-4o-mini.
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO model_budgets (id, organization_id, model, monthly_budget_cents) "
                "VALUES (gen_random_uuid(), :oid, 'gpt-4o-mini', 10)"
            ),
            {"oid": UUID(oid)},
        )
        # Uso de $0.05 (50%) y $0.09 (90%).
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, model, "
                "status, estimated_cost, actual_cost, cost_tags) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'completed', "
                "0.05, 0.05, '{}')"
            ),
            {"oid": UUID(oid)},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, model, "
                "status, estimated_cost, actual_cost, cost_tags) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'completed', "
                "0.04, 0.04, '{}')"
            ),
            {"oid": UUID(oid)},
        )
        await session.commit()
    finally:
        await session.close()

    status = await model_budget_status(UUID(oid), "gpt-4o-mini")
    assert status["allowed"] is True
    assert status["usage_pct"] == pytest.approx(90.0, abs=0.1)
    assert status["throttle_factor"] < 1.0
    assert status["throttle_factor"] >= 0.2

    # Superar el budget → bloqueado.
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, model, "
                "status, estimated_cost, actual_cost, cost_tags) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'completed', "
                "0.03, 0.03, '{}')"
            ),
            {"oid": UUID(oid)},
        )
        await session.commit()
    finally:
        await session.close()

    status2 = await model_budget_status(UUID(oid), "gpt-4o-mini")
    assert status2["allowed"] is False
    assert status2["usage_pct"] == pytest.approx(120.0, abs=0.1)

    listed = await async_client.get(
        f"/api/v1/platform/model-health/budgets?organization_id={oid}", headers=plat
    )
    assert listed.status_code == 200, listed.text
    entry = next(b for b in listed.json()["budgets"] if b["model"] == "gpt-4o-mini")
    assert entry["allowed"] is False


@pytest.mark.asyncio
async def test_circuit_breaker_and_runtime_guard(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-mhc-{uuid4().hex[:8]}@zent.example")

    from src.platform.modelhealth.guardrails import (
        check_circuit,
        record_failure,
        record_success,
        reset_circuit,
    )

    await reset_circuit("zent-test")

    # 2 fallos con umbral 3 → cerrado; 3 → abierto.
    for _ in range(2):
        await record_failure("zent-test")
    state = await check_circuit("zent-test")
    assert state["state"] == "closed"
    assert state["failures"] == 2

    await record_failure("zent-test")
    state = await check_circuit("zent-test")
    assert state["state"] == "open"
    assert state["opened_until"] is not None

    # Éxito → half_open (cooldown activo) y reseteo manual → closed.
    await record_success("zent-test")
    state = await check_circuit("zent-test")
    assert state["state"] == "half_open"

    await reset_circuit("zent-test")
    state = await check_circuit("zent-test")
    assert state["state"] == "closed"
    assert state["failures"] == 0

    # Endpoint de simulación (trip) y reset.
    trip = await async_client.post(
        "/api/v1/platform/model-health/circuits/gpt-4o-mini/trip", headers=plat
    )
    assert trip.status_code == 200, trip.text
    assert trip.json()["state"] == "open"
    circuits = await async_client.get("/api/v1/platform/model-health/circuits", headers=plat)
    entry = next(c for c in circuits.json()["circuits"] if c["model"] == "gpt-4o-mini")
    assert entry["state"] == "open"
    reset = await async_client.post(
        "/api/v1/platform/model-health/circuits/gpt-4o-mini/reset", headers=plat
    )
    assert reset.status_code == 200

    # Runtime guard: circuito abierto bloquea el run sin candidato.
    org = await _create_org(async_client, "MH Circuit Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    from src.agents.runtime.agent_runtime import AgentRuntime
    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from src.infrastructure.llm.provider import LiteLLMProvider

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"mh-a-{uuid4().hex}"},
            json={"name": "MH Agent", "system_prompt": "t", "model": "zent-test", "tools": []},
        )
    ).json()

    await reset_circuit("zent-test")
    for _ in range(5):
        await record_failure("zent-test")

    real_runtime = AgentRuntime(llm_provider=LiteLLMProvider())

    async def fake_loop(request, ctx, config, result):
        result.status = "completed"
        result.answer = "ok"
        result.total_tokens = 10
        result.cost = 0.0001

    real_runtime._run_loop = fake_loop  # type: ignore[method-assign]
    app.dependency_overrides[get_agent_runtime] = lambda: real_runtime
    run = await async_client.post(
        f"/api/v1/agents/{agent['id']}/run",
        headers={**_headers(org), "Idempotency-Key": f"mh-r-{uuid4().hex}"},
        json={"message": "hola"},
    )
    assert run.status_code == 200, run.text
    assert run.json()["answer"] == ""
    assert any("model_circuit_open" in (s.get("detail") or "") for s in run.json().get("steps", []))
    await reset_circuit("zent-test")


@pytest.mark.asyncio
async def test_model_health_dashboard(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-mhd-{uuid4().hex[:8]}@zent.example")

    from src.platform.proxy.inference_proxy import log_inference

    for i in range(4):
        await log_inference(
            organization_id=UUID("00000000-0000-0000-0000-000000000001"),
            deployment_id=None,
            agent_id=None,
            model=f"dash-{uuid4().hex[:6]}",
            backend="openai",
            status="completed" if i < 3 else "error",
            prompt_tokens=50,
            completion_tokens=25,
            latency_ms=100.0 + i * 50,
            cost=0.001,
        )

    dash = await async_client.get("/api/v1/platform/model-health/dashboard?hours=24", headers=plat)
    assert dash.status_code == 200, dash.text
    assert len(dash.json()["models"]) > 0
    first = dash.json()["models"][0]
    assert first["requests"] >= 1
    assert first["circuit_state"] in ("closed", "open", "half_open")

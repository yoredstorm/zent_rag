# =============================================================================
# Multi-Tenant Notifications & Webhooks v2 (PROMPT 37)
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
            "email": f"nt-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"nt-{uuid4().hex}",
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
async def test_in_app_center_and_preferences(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "NT Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.notifyv2.notifications import notify

    await notify(UUID(org["organization_id"]), "quota.exceeded", "Cuota agotada", "Se bloqueó un run")
    await notify(UUID(org["organization_id"]), "invoice.paid", "Factura pagada", "INV-1 confirmada")

    listed = await async_client.get("/api/v1/notifications", headers=h)
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 2

    unread = await async_client.get("/api/v1/notifications/unread-count", headers=h)
    assert unread.json()["count"] == 2

    first = listed.json()["notifications"][0]
    read = await async_client.post(f"/api/v1/notifications/{first['id']}/read", headers=h)
    assert read.status_code == 200, read.text
    unread2 = await async_client.get("/api/v1/notifications/unread-count", headers=h)
    assert unread2.json()["count"] == 1

    unread_only = await async_client.get("/api/v1/notifications?unread_only=true", headers=h)
    assert unread_only.json()["count"] == 1

    read_all = await async_client.post("/api/v1/notifications/read-all", headers=h)
    assert read_all.status_code == 200, read_all.text
    assert read_all.json()["marked"] == 1

    arch = await async_client.post(f"/api/v1/notifications/{first['id']}/archive", headers=h)
    assert arch.status_code == 200, arch.text

    # Preferencias: desactivar in_app → notify no inserta.
    prefs = await async_client.put(
        "/api/v1/notifications/preferences",
        headers=h,
        json={"channels": {"in_app": False, "email": True, "webhook": True}},
    )
    assert prefs.status_code == 200, prefs.text
    assert prefs.json()["channels"]["in_app"] is False

    await notify(UUID(org["organization_id"]), "test.ping", "Ping", "sin in-app")
    listed2 = await async_client.get("/api/v1/notifications?event_type=test.ping", headers=h)
    assert listed2.json()["count"] == 0

    # Re-activar.
    await async_client.put(
        "/api/v1/notifications/preferences",
        headers=h,
        json={"channels": {"in_app": True, "email": True, "webhook": True}},
    )


@pytest.mark.asyncio
async def test_webhook_deliveries_with_retry_backoff(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "NT WH Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-ntw-{uuid4().hex[:8]}@zent.example")

    # Suscripción con URL inválida (fallará el POST → reintentos).
    sub = await async_client.post(
        "/api/v1/webhooks",
        headers={**_headers(org), "Idempotency-Key": f"nt-s-{uuid4().hex}"},
        json={"event_type": "invoice.paid", "url": "http://127.0.0.1:1/nonexistent", "secret": "test-secret"},
    )
    assert sub.status_code == 201, sub.text
    sub_id = sub.json()["id"]

    from src.platform.notifyv2.notifications import notify

    await notify(UUID(org["organization_id"]), "invoice.paid", "Factura pagada", "INV-2")

    deliveries = await async_client.get("/api/v1/notifications/deliveries", headers=h)
    assert deliveries.status_code == 200, deliveries.text
    mine = [d for d in deliveries.json()["deliveries"] if d["subscription_id"] == sub_id]
    assert len(mine) == 1
    delivery = mine[0]
    assert delivery["status"] == "pending"
    assert delivery["attempts"] == 0

    # Procesar → falla → retrying con backoff y attempts=1.
    from src.platform.notifyv2.notifications import process_deliveries

    result = await process_deliveries()
    assert any(p["delivery_id"] == delivery["id"] and p["status"] == "retrying" for p in result["processed"])

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, next_attempt_at, last_status_code "
                    "FROM webhook_deliveries WHERE id = :did"
                ),
                {"did": UUID(delivery["id"])},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row.status == "retrying"
    assert row.attempts == 1
    assert row.next_attempt_at is not None and row.next_attempt_at > __import__("datetime").datetime.now(__import__("datetime").timezone.utc)

    # Repetir proceso inmediatamente → no se reintenta (backoff).
    result2 = await process_deliveries()
    assert all(p["delivery_id"] != delivery["id"] for p in result2["processed"])

    # Dashboard platform.
    dash = await async_client.get("/api/v1/platform/notifications/deliveries/status?hours=24", headers=plat)
    assert dash.status_code == 200, dash.text
    entry = next(s for s in dash.json()["subscriptions"] if s["subscription_id"] == sub_id)
    assert entry["total"] == 1
    assert entry["retrying"] == 1  # primer intento fallido → backoff activo
    assert entry["failed"] == 0  # aún no agotó reintentos
    assert entry["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_webhook_delivery_success_with_signature(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "NT WH Ok Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    received: dict = {}

    import asyncio

    async def handle(reader, writer):
        data = await reader.read(65536)
        raw = data.decode(errors="replace")
        lines = raw.split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                headers[k.strip().lower()] = v.strip()
        body = raw.split("\r\n\r\n", 1)[1] if "\r\n\r\n" in raw else ""
        received["signature"] = headers.get("x-zent-signature", "")
        received["payload"] = body
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n{\"ok\":true}")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 8766)
    port = 8766
    await asyncio.sleep(0.2)

    try:
        sub = await async_client.post(
            "/api/v1/webhooks",
            headers={**_headers(org), "Idempotency-Key": f"nt-s2-{uuid4().hex}"},
            json={"event_type": "invoice.paid", "url": f"http://127.0.0.1:{port}/hook", "secret": "secret-test"},
        )
        assert sub.status_code == 201, sub.text

        from src.platform.notifyv2.notifications import notify, process_deliveries

        await notify(UUID(org["organization_id"]), "invoice.paid", "Factura pagada", "INV-3")

        result = await process_deliveries()
        assert any(p["status"] == "delivered" and p["status_code"] == 200 for p in result["processed"])
        assert received.get("signature", "").startswith("sha256=")
        assert "Factura pagada" in received.get("payload", "")

        # El payload firmado verifica con el secreto.
        import hashlib
        import hmac

        body = received["payload"]
        sig = received["signature"].split("=", 1)[1]
        expected = hmac.new(b"secret-test", body.encode(), hashlib.sha256).hexdigest()
        assert hmac.compare_digest(sig, expected)
    finally:
        server.close()
        await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_trigger_endpoint_and_quota_hook(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "NT Trig Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-ntt-{uuid4().hex[:8]}@zent.example")

    trig = await async_client.post(
        "/api/v1/platform/notifications/trigger",
        headers=plat,
        json={"organization_id": org["organization_id"], "event_type": "usage.alert", "title": "Alerta de uso"},
    )
    assert trig.status_code == 200, trig.text
    assert trig.json()["in_app"] is True

    h = _headers(org)
    listed = await async_client.get("/api/v1/notifications?event_type=usage.alert", headers=h)
    assert listed.json()["count"] == 1

    # Hook de cuota: override con monthly_tokens=0 → preflight lanza.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"nt-a-{uuid4().hex}"},
            json={"name": "NT Agent", "system_prompt": "t", "model": "gpt-4o-mini"},
        )
    ).json()

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_quotas (organization_id, monthly_tokens) "
                "VALUES (:oid, 100) ON CONFLICT (organization_id) DO UPDATE SET "
                "monthly_tokens = 100"
            ),
            {"oid": UUID(org["organization_id"])},
        )
        await session.commit()
        agent_row = (
            await session.execute(
                text(
                    "SELECT id, name, model, status, config_json FROM agents "
                    "WHERE organization_id = :oid ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).fetchone()
        version = (
            await session.execute(
                text(
                    "SELECT config_snapshot FROM agent_versions "
                    "WHERE agent_id = :aid ORDER BY created_at DESC LIMIT 1"
                ),
                {"aid": agent_row.id},
            )
        ).fetchone()
    finally:
        await session.close()

    from src.agents.runtime.agent_runtime import AgentRunRequest, AgentRuntime
    from src.api.deps import get_agent_runtime
    from src.api.main import app
    from src.infrastructure.llm.provider import LiteLLMProvider

    real_runtime = AgentRuntime(llm_provider=LiteLLMProvider())

    async def fake_loop(request, ctx, config, result):
        result.status = "completed"
        result.answer = "ok"
        result.total_tokens = 10
        result.cost = 0.0001

    real_runtime._run_loop = fake_loop  # type: ignore[method-assign]
    app.dependency_overrides[get_agent_runtime] = lambda: real_runtime
    # Llamada directa al runtime: el preflight dispara quota.exceeded
    # (el middleware HTTP bloquearía el request con 402 antes del runtime).
    from src.core.domain.entities import Agent as _Agent
    from src.platform.deployments.versions import resolve_agent

    agent_entity = _Agent(
        id=agent_row.id,
        organization_id=UUID(org["organization_id"]),
        name=agent_row.name,
        model=agent_row.model,
        status=agent_row.status,
        config_json=agent_row.config_json or {},
        system_prompt="t",
    )
    snapshot = version.config_snapshot if version else {}
    # Consumo previo de 500 tokens > límite 100 → preflight lanza.
    from src.platform.usage.usage_engine import get_usage_counters

    await get_usage_counters().record(UUID(org["organization_id"]), uuid4(), tokens=500, cost=0.01)
    run_result = await real_runtime.run(
        AgentRunRequest(
            agent=resolve_agent(agent_entity, snapshot),
            message="hola",
            user_id=uuid4(),
            trace_id="quota-hook-test",
        )
    )

    listed2 = await async_client.get("/api/v1/notifications?event_type=quota.exceeded", headers=h)
    assert listed2.status_code == 200, listed2.text
    assert listed2.json()["count"] >= 1

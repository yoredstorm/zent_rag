# =============================================================================
# AI Chat Analytics & Conversational Insights v2 (PROMPT 45)
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
            "email": f"ci-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"ci-{uuid4().hex}",
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


async def _chat_org(client: AsyncClient, org: dict, messages: list[str]) -> str:
    from src.platform.copilot.copilot import chat

    session_id = None
    for msg in messages:
        out = await chat(UUID(org["organization_id"]), None, msg, session_id)
        session_id = UUID(out["session_id"])
    return str(session_id)


@pytest.mark.asyncio
async def test_funnel_and_resolution(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CI Funnel Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # 2 sesiones: una con 2+ mensajes + feedback (resuelta), otra de 1 mensaje.
    from src.platform.copilot.copilot import chat

    out = await chat(UUID(org["organization_id"]), None, "cuál es el precio del plan pro?")
    await chat(UUID(org["organization_id"]), None, "y cuánto cuesta el anual?", UUID(out["session_id"]))
    await async_client.post(
        "/api/v1/feedback",
        headers={**_headers(org), "Idempotency-Key": f"ci-f-{uuid4().hex}"},
        json={"run_id": None, "rating": "up", "reason": "other"},
    )
    await chat(UUID(org["organization_id"]), None, "hola")

    funnel = await async_client.get("/api/v1/chat-insights/funnel", headers=h)
    assert funnel.status_code == 200, funnel.text
    body = funnel.json()
    assert body["total_sessions"] >= 2
    assert body["total_messages"] >= 4
    assert body["active_sessions"] >= 1
    assert body["resolved_sessions"] >= 1
    assert body["resolution_rate"] > 0


@pytest.mark.asyncio
async def test_topic_analysis_and_escalation(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CI Topics Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.copilot.copilot import chat

    await chat(UUID(org["organization_id"]), None, "cuánto cuesta el plan pro?")
    await chat(UUID(org["organization_id"]), None, "quiero hablar con un humano por favor")
    await chat(UUID(org["organization_id"]), None, "cómo subo un pdf a la base de conocimiento?")

    topics = await async_client.get("/api/v1/chat-insights/topics", headers=h)
    assert topics.status_code == 200, topics.text
    body = topics.json()
    assert body["total_user_messages"] == 3
    names = {t["topic"] for t in body["topics"]}
    assert "ventas" in names  # precio/costo
    assert "kb" in names  # pdf/base de conocimiento

    friction = await async_client.get("/api/v1/chat-insights/friction", headers=h)
    events = friction.json()["events"]
    assert events.get("escalated", 0) >= 1


@pytest.mark.asyncio
async def test_friction_detection(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CI Friction Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.copilot.copilot import chat

    # Sesión con 4 mensajes sin feedback → repetitiva.
    sid = None
    for i in range(4):
        out = await chat(UUID(org["organization_id"]), None, f"no funciona el deploy {i}", sid)
        sid = UUID(out["session_id"])

    friction = await async_client.get("/api/v1/chat-insights/friction", headers=h)
    assert friction.status_code == 200, friction.text
    body = friction.json()
    assert len(body["repetitive_sessions"]) >= 1
    assert body["repetitive_sessions"][0]["messages"] == 4
    assert body["summary"]["friction_index"] > 0


@pytest.mark.asyncio
async def test_channel_comparison(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CI Chan Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.copilot.copilot import chat

    await chat(UUID(org["organization_id"]), None, "hola desde copilot")

    session = await get_async_session()
    try:
        for endpoint, latency in (
            ("/api/v1/deployments/px/query", 350),
            ("/api/v1/deployments/px/query", 550),
            ("/api/v1/widget/chat", 800),
        ):
            await session.execute(
                text(
                    "INSERT INTO api_logs (id, organization_id, request_id, endpoint, "
                    "method, status, latency_ms) "
                    "VALUES (gen_random_uuid(), :oid, :rid, :ep, 'POST', 200, :lat)"
                ),
                {"oid": UUID(org["organization_id"]), "rid": uuid4().hex, "ep": endpoint, "lat": latency},
            )
        await session.commit()
    finally:
        await session.close()

    channels = await async_client.get("/api/v1/chat-insights/channels", headers=h)
    assert channels.status_code == 200, channels.text
    by_name = {c["channel"]: c for c in channels.json()["channels"]}
    assert by_name["api"]["messages"] == 2
    assert by_name["api"]["avg_latency_ms"] == 450.0
    assert by_name["widget"]["messages"] == 1
    assert by_name["copilot"]["messages"] >= 1


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CI Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-cid-{uuid4().hex[:8]}@zent.example")

    from src.platform.copilot.copilot import chat

    await chat(UUID(org["organization_id"]), None, "necesito ayuda con la facturación")

    dash = await async_client.get("/api/v1/platform/chat-insights/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["sessions_30d"] >= 1
    assert body["messages_30d"] >= 1
    assert body["organizations_using"] >= 1
    assert any(t["topic"] == "facturación" for t in body["top_topics"])

# =============================================================================
# AI Copilot & Assistant Platform v2 (PROMPT 43)
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
            "email": f"cp-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"cp-{uuid4().hex}",
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
async def test_marketplace_install_remove(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP Market Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    market = await async_client.get("/api/v1/copilot/marketplace", headers=h)
    assert market.status_code == 200, market.text
    assert len(market.json()["agents"]) == 5
    assert market.json()["agents"][0]["featured"] is True

    installed = await async_client.post(
        "/api/v1/copilot/marketplace/install",
        headers={**_headers(org), "Idempotency-Key": f"cp-i-{uuid4().hex}"},
        json={"slug": "customer-support"},
    )
    assert installed.status_code == 200, installed.text
    agent_id = installed.json()["agent_id"]

    # El agente se creó en el tenant con el prompt del template.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        agent = (
            await session.execute(
                text("SELECT system_prompt, config_json FROM agents WHERE id = :aid"),
                {"aid": UUID(agent_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    assert "soporte" in agent.system_prompt.lower()
    assert agent.config_json.get("marketplace_slug") == "customer-support"

    # Re-instalar → 400 (ya instalado).
    dup = await async_client.post(
        "/api/v1/copilot/marketplace/install",
        headers={**_headers(org), "Idempotency-Key": f"cp-i2-{uuid4().hex}"},
        json={"slug": "customer-support"},
    )
    assert dup.status_code == 400

    installs = await async_client.get("/api/v1/copilot/marketplace/installs", headers=h)
    assert installs.status_code == 200, installs.text
    assert len(installs.json()["installs"]) == 1
    assert installs.json()["installs"][0]["slug"] == "customer-support"

    removed = await async_client.post(
        f"/api/v1/copilot/marketplace/{installs.json()['installs'][0]['id']}/remove",
        headers={**_headers(org)},
    )
    assert removed.json()["removed"] is True
    session = await get_async_session()
    try:
        status = (
            await session.execute(text("SELECT status FROM agents WHERE id = :aid"), {"aid": UUID(agent_id)})
        ).scalar()
    finally:
        await session.close()
    assert status == "archived"


@pytest.mark.asyncio
async def test_chat_routing_and_sessions(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP Chat Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    # Crear un agente para que el router lo resuelva.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"cp-a-{uuid4().hex}"},
            json={"name": "Soporte Z", "system_prompt": "soporte", "model": "gpt-4o-mini"},
        )
    ).json()

    reply = await async_client.post(
        "/api/v1/copilot/chat",
        headers={**_headers(org), "Idempotency-Key": f"cp-c-{uuid4().hex}"},
        json={"message": "necesito desplegar mi agente en producción", "title": "deploy"},
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["intent"] == "deployments"
    assert body["resolved_agent_id"] == agent["id"]
    session_id = body["session_id"]

    # Fallback para saludos.
    fb = await async_client.post(
        "/api/v1/copilot/chat",
        headers={**_headers(org), "Idempotency-Key": f"cp-c2-{uuid4().hex}"},
        json={"message": "hola, buenos días", "session_id": session_id},
    )
    assert fb.json()["intent"] is None

    sessions = await async_client.get("/api/v1/copilot/sessions", headers=h)
    assert len(sessions.json()["sessions"]) == 1

    msgs = await async_client.get(f"/api/v1/copilot/sessions/{session_id}", headers=h)
    assert msgs.status_code == 200, msgs.text
    roles = [m["role"] for m in msgs.json()["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]

    # Telemetría de uso registrada.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        usage = (
            await session.execute(
                text("SELECT events FROM assistant_usage WHERE organization_id = :oid AND assistant_key = 'copilot:intent:deployments'"),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(usage) == 1


@pytest.mark.asyncio
async def test_automation_suggestions(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP Auto Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.copilot.copilot import chat

    for i in range(4):
        await chat(
            UUID(org["organization_id"]),
            None,
            f"pregunta #{i}: cómo funciona la facturación y el pago del plan",
        )

    sugg = await async_client.get("/api/v1/copilot/automations/suggest", headers=h)
    assert sugg.status_code == 200, sugg.text
    suggestions = sugg.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["intent"] == "billing"
    assert suggestions[0]["repeats"] == 4
    assert len(suggestions[0]["sample_questions"]) == 3


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CP Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-cpd-{uuid4().hex[:8]}@zent.example")

    from src.platform.copilot.copilot import chat, install_marketplace

    await install_marketplace(UUID(org["organization_id"]), "sales-qualifier")
    await chat(UUID(org["organization_id"]), None, "¿cuánto cuesta el plan pro?")

    dash = await async_client.get("/api/v1/platform/copilot/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["sessions"] >= 1
    assert body["organizations_using"] >= 1
    assert any(i["slug"] == "sales-qualifier" and i["active"] >= 1 for i in body["installs"])
    assert any(t["key"] == "copilot:intent:billing" for t in body["top_assistants"])
    assert any(i["intent"] == "billing" for i in body["intents"])

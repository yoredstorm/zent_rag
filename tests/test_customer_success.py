# =============================================================================
# Customer Success (PROMPT 12) — onboarding, branding, reportes, conversión
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
            "email": f"cs-{uuid4().hex[:8]}@example.com",
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


async def _seed_agent_and_deploy(client: AsyncClient, org: dict) -> tuple[dict, dict]:
    agent = (
        await client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"cs-{uuid4().hex}"},
            json={"name": "CS Agent", "system_prompt": "t", "model": "gpt-4o-mini", "tools": []},
        )
    ).json()
    version = (
        await client.post(f"/api/v1/agents/{agent['id']}/versions", headers=_headers(org), json={})
    ).json()
    await client.post(
        f"/api/v1/agents/{agent['id']}/versions/{version['id']}/promote",
        headers=_headers(org),
        json={"status": "ready"},
    )
    envs = (await client.get("/api/v1/environments", headers=_headers(org))).json()["environments"]
    prod = next(e for e in envs if e["slug"] == "production")
    dep = (
        await client.post(
            "/api/v1/deployments",
            headers={**_headers(org), "Idempotency-Key": f"cs-dep-{uuid4().hex}"},
            json={
                "agent_id": agent["id"],
                "agent_version_id": version["id"],
                "environment_id": prod["id"],
            },
        )
    ).json()
    return agent, dep


@pytest.mark.asyncio
async def test_onboarding_checklist(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CS Onboarding Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-cs-{uuid4().hex[:8]}@zent.example")

    # Tenant: checklist inicial (workspace + api_key por el trial).
    resp = await async_client.get("/api/v1/organizations/onboarding", headers=h)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert {i["key"] for i in items if i["done"]} == {"workspace", "api_key"}

    # Crear agente + deployment healthy → items flipean.
    _agent, dep = await _seed_agent_and_deploy(async_client, org)
    assert dep["status"] == "healthy"

    # API key.
    key = await async_client.post(
        "/api/v1/organizations/api-keys",
        headers={**h, "Idempotency-Key": f"cs-key-{uuid4().hex}"},
        json={"name": "cs-key"},
    )
    assert key.status_code == 200, key.text

    # Plataforma: checklist refleja el progreso.
    plat_view = await async_client.get(
        f"/api/v1/platform/customer-success/onboarding?organization_id={org['organization_id']}",
        headers=plat,
    )
    assert plat_view.status_code == 200, plat_view.text
    done_keys = {i["key"] for i in plat_view.json()["items"] if i["done"]}
    assert "agent" in done_keys and "deployment" in done_keys and "api_key" in done_keys


@pytest.mark.asyncio
async def test_branding_roundtrip(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CS Branding Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    put = await async_client.put(
        "/api/v1/organizations/branding",
        headers=h,
        json={"branding": {"logo_url": "https://cdn.example/logo.png", "primary_color": "#0ea5e9"}},
    )
    assert put.status_code == 200, put.text
    got = await async_client.get("/api/v1/organizations/branding", headers=h)
    assert got.status_code == 200, got.text
    assert got.json()["branding"]["primary_color"] == "#0ea5e9"


@pytest.mark.asyncio
async def test_report_subscriptions_and_send(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CS Reports Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-rep-{uuid4().hex[:8]}@zent.example")

    # Tenant: suscribirse.
    sub = await async_client.post(
        "/api/v1/organizations/reports",
        headers=h,
        json={"email": "finance@tenant.example", "frequency": "monthly"},
    )
    assert sub.status_code == 201, sub.text

    listed = await async_client.get("/api/v1/organizations/reports", headers=h)
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    sub_id = listed.json()["subscriptions"][0]["id"]

    # Reporte construido con contenido real (sin SMTP → skipped).
    sent = await async_client.post(
        f"/api/v1/platform/customer-success/reports/{sub_id}/send-now", headers=plat, json={}
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "skipped_no_smtp"

    # Plataforma ve la suscripción.
    all_subs = await async_client.get("/api/v1/platform/customer-success/reports", headers=plat)
    assert all_subs.status_code == 200, all_subs.text
    assert any(s["id"] == sub_id for s in all_subs.json()["subscriptions"])

    # Cancelar (tenant).
    deleted = await async_client.delete(f"/api/v1/organizations/reports/{sub_id}", headers=h)
    assert deleted.status_code == 200, deleted.text
    listed2 = await async_client.get("/api/v1/organizations/reports", headers=h)
    assert listed2.json()["count"] == 0


@pytest.mark.asyncio
async def test_conversion_analytics(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-conv-{uuid4().hex[:8]}@zent.example")

    # Seed: un trial y un active (paid) de referencia.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        pro_plan = (
            await session.execute(text("SELECT id FROM plans WHERE name = 'pro' LIMIT 1"))
        ).scalar()
        assert pro_plan is not None
        # Convierte una suscripción trial existente en "paid activa" (una sub por org).
        await session.execute(
            text(
                "UPDATE subscriptions SET status = 'active', plan_id = :plan "
                "WHERE organization_id = (SELECT organization_id FROM subscriptions "
                "WHERE status = 'trialing' ORDER BY created_at LIMIT 1) "
                "AND plan_id <> :plan"
            ),
            {"plan": pro_plan},
        )
        await session.commit()
    finally:
        await session.close()

    conv = await async_client.get("/api/v1/platform/customer-success/conversion", headers=plat)
    assert conv.status_code == 200, conv.text
    body = conv.json()
    assert body["trials"] >= 1
    assert body["paid_active"] >= 1
    assert body["conversion_rate_pct"] is not None
    plans = {p["plan"] for p in body["by_plan"]}
    assert "pro" in plans


@pytest.mark.asyncio
async def test_invite_email_flag(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "CS Invite Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    inv = await async_client.post(
        "/api/v1/organizations/invites",
        headers={**h, "Idempotency-Key": f"cs-inv-{uuid4().hex}"},
        json={"email": f"newbie-{uuid4().hex[:8]}@example.com", "role": "member"},
    )
    assert inv.status_code == 201, inv.text
    # Sin SMTP configurado → fail-soft: token se entrega igual y email marcado.
    assert inv.json()["email_sent"] is False
    assert inv.json()["token"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT email_sent, delivery_status FROM organization_invites "
                    "WHERE id = :iid"
                ),
                {"iid": UUID(inv.json()["id"])},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row.email_sent is False
    assert row.delivery_status == "skipped_no_smtp"

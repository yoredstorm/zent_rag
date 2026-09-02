# =============================================================================
# Developer Experience (PROMPT 23) — SDK reference, webhooks, changelog
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
            "email": f"dev-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"dev-{uuid4().hex}",
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
async def test_sdk_reference(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Dev SDK Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)
    plat = await _platform_admin(async_client, f"padmin-dev-{uuid4().hex[:8]}@zent.example")

    ref = await async_client.get("/api/v1/dev/sdk-reference", headers=h)
    assert ref.status_code == 200, ref.text
    body = ref.json()
    assert body["base_url"].startswith("https://")
    assert len(body["endpoints"]) >= 4
    first = body["endpoints"][0]
    for lang in ("python", "javascript", "csharp", "java", "php"):
        assert lang in first["snippets"]
        assert "httpx" in first["snippets"]["python"] or "requests" in first["snippets"]["python"]
    assert "Bearer" in first["auth"] or "Authorization" in first["auth"]

    plat_ref = await async_client.get("/api/v1/platform/dev/sdk-reference", headers=plat)
    assert plat_ref.status_code == 200, plat_ref.text


@pytest.mark.asyncio
async def test_changelog_and_public_status(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-dev2-{uuid4().hex[:8]}@zent.example")

    pub = await async_client.get("/api/v1/dev/changelog")
    assert pub.status_code == 200, pub.text
    entries = pub.json()["changelog"]
    assert len(entries) >= 3  # builtins sembrados
    versions = {e["version"] for e in entries}
    assert "v2.4.0" in versions and "v2.6.0" in versions

    # Público sin auth: status.
    status = await async_client.get("/api/v1/dev/status")
    assert status.status_code == 200, status.text
    assert status.json()["status"] in ("ok", "degraded", "down")
    assert status.json()["api_version"]

    # Plataforma agrega entrada.
    added = await async_client.post(
        "/api/v1/platform/dev/changelog",
        headers=plat,
        json={"version": "v2.7.0", "title": "Nueva release", "body": "Descripción", "is_public": True},
    )
    assert added.status_code == 201, added.text
    assert added.json()["version"] == "v2.7.0"

    # El status incluye las releases recientes.
    status2 = await async_client.get("/api/v1/dev/status")
    assert any(r["version"] == "v2.7.0" for r in status2.json()["latest_releases"])


@pytest.mark.asyncio
async def test_webhook_crud_and_dispatch(async_client: AsyncClient, monkeypatch) -> None:
    import src.platform.devportal.sdk as sdk_mod

    org = await _create_org(async_client, "Dev Webhook Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/webhooks",
        headers=h,
        json={"event_type": "agent_run", "url": "https://hooks.corp.example/zent", "secret": "my-secret-123"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    webhook_id = body["id"]
    assert body["secret"] == "my-secret-123"

    listed = await async_client.get("/api/v1/webhooks", headers=h)
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    assert listed.json()["webhooks"][0]["event_type"] == "agent_run"

    # Secreto cifrado en reposo.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        enc = (
            await session.execute(
                text("SELECT secret_enc FROM webhook_subscriptions WHERE id = :wid"),
                {"wid": UUID(webhook_id)},
            )
        ).scalar()
    finally:
        await session.close()
    assert "my-secret-123" not in enc

    # Dispatch con firma HMAC (monkeypatch del POST).
    received: list[dict] = []

    async def _fake_post(url: str, secret: str, payload: dict) -> bool:
        received.append({"url": url, "secret": secret, "payload": payload})
        return True

    monkeypatch.setattr(sdk_mod, "_post_webhook", _fake_post)
    from src.platform.devportal.sdk import dispatch_event

    delivered = await dispatch_event("agent_run", UUID(org["organization_id"]), {"model": "gpt-4o-mini"})
    assert delivered == 1
    assert received[0]["secret"] == "my-secret-123"
    assert received[0]["payload"]["event"] == "agent_run"
    assert received[0]["payload"]["model"] == "gpt-4o-mini"

    # Contadores actualizados.
    listed2 = await async_client.get("/api/v1/webhooks", headers=h)
    assert listed2.json()["webhooks"][0]["delivery_count"] == 1
    assert listed2.json()["webhooks"][0]["last_delivered_at"] is not None

    # Ping de prueba.
    ping = await async_client.post(f"/api/v1/webhooks/{webhook_id}/test", headers=h, json={})
    assert ping.status_code == 200, ping.text
    assert ping.json()["status"] == "delivered"

    # Delete.
    deleted = await async_client.delete(f"/api/v1/webhooks/{webhook_id}", headers=h)
    assert deleted.status_code == 200, deleted.text
    listed3 = await async_client.get("/api/v1/webhooks", headers=h)
    assert listed3.json()["count"] == 0

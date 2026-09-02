# =============================================================================
# Security Center (PROMPT 20) — posture, secretos, leaks
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
            "email": f"sec-{uuid4().hex[:8]}@example.com",
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
async def test_posture_score(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sec Posture Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-sec-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Org fresca: bajo.
    p0 = await async_client.get(
        f"/api/v1/platform/security/posture?organization_id={oid}", headers=plat
    )
    assert p0.status_code == 200, p0.text
    body0 = p0.json()
    assert body0["score"] < 60
    names = {c["name"] for c in body0["components"]}
    assert "sso_enabled" in names and "key_rotation_policy" in names and "pii_masking" in names

    # Endurecer: SSO + SCIM + key policy + DSR + residencia + PII + webhook.
    h = {
        "Authorization": f"Bearer {org['session']}",
        "X-Organization-Id": org["organization_id"],
        "Idempotency-Key": f"sec-{uuid4().hex}",
    }
    await async_client.put("/api/v1/auth/sso/config", headers=h, json={
        "enabled": True, "issuer": "https://idp.example.com", "client_id": "x", "client_secret": "s"})
    await async_client.post("/api/v1/auth/sso/scim-token", headers=h, json={})
    await async_client.put("/api/v1/auth/sso/key-policy", headers=h, json={"max_age_days": 90})
    await async_client.put(
        f"/api/v1/platform/governance/organizations/{oid}",
        headers=plat,
        json={"dsr_contact_email": "dsr@corp.example", "data_residency_region": "us-east-1"},
    )
    await async_client.put(
        f"/api/v1/platform/ai-governance/organizations/{oid}",
        headers=plat,
        json={"pii_masking_enabled": True},
    )
    await async_client.put(
        f"/api/v1/platform/organizations/{oid}/ops-webhook",
        headers=plat,
        json={"url": "https://hooks.example.test/ops", "enabled": True},
    )

    p1 = await async_client.get(
        f"/api/v1/platform/security/posture?organization_id={oid}", headers=plat
    )
    assert p1.json()["score"] >= 70, p1.json()

    # Todas las orgs.
    all_p = await async_client.get("/api/v1/platform/security/posture", headers=plat)
    assert all_p.status_code == 200, all_p.text
    assert len(all_p.json()["organizations"]) >= 1


@pytest.mark.asyncio
async def test_secret_scan_and_findings(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sec Secrets Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-secs-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Scan de un texto.
    text = "La key es zent_sk_live_abc123def456ghi789jkl y el OpenAI sk-1234567890abcdefghijklmnopqrs"
    scan = await async_client.post(
        "/api/v1/platform/security/scan-secrets", headers=plat, json={"text": text}
    )
    assert scan.status_code == 200, scan.text
    detected = scan.json()["detected"]
    assert detected.get("api_key") == 1
    assert detected.get("openai_key") == 1

    # Agente con secreto en el prompt → scan lo encuentra.
    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={
                "Authorization": f"Bearer {org['session']}",
                "X-Organization-Id": org["organization_id"],
                "Idempotency-Key": f"sec-ag-{uuid4().hex}",
            },
            json={
                "name": "Leaky Agent",
                "system_prompt": "Config: password=hunter2 y SMTP_PASSWORD=supersecret",
                "model": "gpt-4o-mini",
                "tools": [],
            },
        )
    ).json()

    run = await async_client.post(
        f"/api/v1/platform/security/scan?organization_id={oid}", headers=plat, json={}
    )
    assert run.status_code == 200, run.text
    created = {f["type"] for f in run.json()["findings_created"]}
    assert "secret_in_prompt" in created

    findings = await async_client.get(
        f"/api/v1/platform/security/findings?organization_id={oid}", headers=plat
    )
    assert findings.status_code == 200, findings.text
    assert findings.json()["count"] >= 1
    mine = next(f for f in findings.json()["findings"] if f["target_id"] == agent["id"])
    assert mine["finding_type"] == "secret_in_prompt"
    assert mine["severity"] == "critical"
    assert "password" in mine["detail"] or "SMTP_PASSWORD" in mine["detail"]

    # Dedupe: re-scan no duplica.
    run2 = await async_client.post(
        f"/api/v1/platform/security/scan?organization_id={oid}", headers=plat, json={}
    )
    assert run2.json()["count"] == 0

    # Resolver.
    resolved = await async_client.post(
        f"/api/v1/platform/security/findings/{mine['id']}/resolve", headers=plat, json={}
    )
    assert resolved.status_code == 200, resolved.text
    final = await async_client.get(
        f"/api/v1/platform/security/findings?organization_id={oid}", headers=plat
    )
    assert final.json()["findings"][0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_api_key_leak_and_revoke(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sec Leak Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-secl-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    key = (
        await async_client.post(
            "/api/v1/organizations/api-keys",
            headers={
                "Authorization": f"Bearer {org['session']}",
                "X-Organization-Id": org["organization_id"],
                "Idempotency-Key": f"sec-k-{uuid4().hex}",
            },
            json={"name": "leak-test"},
        )
    ).json()
    key_id = key["key_id"]

    # api_log con error que contiene el prefijo de key.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        log_id = (
            await session.execute(
                text(
                    "INSERT INTO api_logs (request_id, organization_id, deployment_id, "
                    "api_key_id, endpoint, method, status, latency_ms, tokens, cost, "
                    "error, created_at) "
                    "VALUES (gen_random_uuid(), :oid, NULL, NULL, '/query', 'POST', 401, "
                    "10.0, 0, 0, 'invalid token zent_sk_live_exposedtoken123456', NOW()) "
                    "RETURNING id"
                ),
                {"oid": UUID(oid)},
            )
        ).scalar()
        await session.commit()
    finally:
        await session.close()

    run = await async_client.post(
        f"/api/v1/platform/security/scan?organization_id={oid}", headers=plat, json={}
    )
    types = {f["type"] for f in run.json()["findings_created"]}
    assert "api_key_leak" in types

    # Revoke one-click de la key.
    revoked = await async_client.post(
        f"/api/v1/platform/security/keys/{key_id}/revoke", headers=plat, json={}
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    # La key ya no está activa.
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository

    after = await PostgresApiKeyRepository().get_key(UUID(key_id))
    assert after.is_active is False

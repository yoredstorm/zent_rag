# =============================================================================
# Enterprise (PROMPT 09) — API keys v2 (rotate/expiry/usage), SCIM 2.0, SSO OIDC
# =============================================================================
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"ent-{uuid4().hex[:8]}@example.com",
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


def _scim_headers(org_id: str, token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org_id,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# API keys v2
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_api_key_rotate_and_usage(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KeysV2 Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/organizations/api-keys",
        headers=h,
        json={"name": "prod-backend", "scopes": ["agents:execute"], "environment": "live"},
    )
    assert created.status_code == 200, created.text
    old_token = created.json()["token"]
    key_id = created.json()["key_id"]

    # Rotar: la vieja se revoca, la nueva funciona.
    rotated = await async_client.post(
        f"/api/v1/organizations/api-keys/{key_id}/rotate", headers=h, json={}
    )
    assert rotated.status_code == 200, rotated.text
    new_token = rotated.json()["token"]
    assert new_token != old_token
    assert rotated.json()["scopes"] == ["agents:execute"]

    # La clave vieja ya no autentica.
    bad = await async_client.get(
        "/api/v1/agents", headers={"Authorization": f"Bearer {old_token}"}
    )
    assert bad.status_code == 401, bad.text
    # La nueva sí (scope agents:execute → GET /agents requiere agents:read; usamos
    # el public query path que acepta agents:execute vía deployments... simplificamos:
    # comprobamos que valida contra la org correcta con el scope esperado).
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    ctx = await billing.validate_token(new_token)
    assert ctx.organization_id == UUID(org["organization_id"])
    assert "agents:execute" in ctx.scopes

    # Auditoría del rotate.
    audit = await async_client.get(
        "/api/v1/audit-logs?resource_type=api_key&limit=20", headers=h
    )
    assert audit.status_code == 200, audit.text
    assert any(e["action"] == "apikey.rotated" for e in audit.json()["entries"])

    # Uso por key (seed api_logs).
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM api_logs WHERE api_key_id = :kid"),
            {"kid": UUID(key_id)},
        )
        for _ in range(9):
            await session.execute(
                text(
                    "INSERT INTO api_logs (request_id, organization_id, deployment_id, "
                    "api_key_id, endpoint, method, status, latency_ms, tokens, cost, created_at) "
                    "VALUES (gen_random_uuid(), :oid, NULL, :kid, '/query', 'POST', 200, "
                    "900.0, 50, 0.0001, NOW() - INTERVAL '1 hour')"
                ),
                {"oid": UUID(org["organization_id"]), "kid": UUID(key_id)},
            )
        await session.execute(
            text(
                "INSERT INTO api_logs (request_id, organization_id, deployment_id, "
                "api_key_id, endpoint, method, status, latency_ms, tokens, cost, created_at) "
                "VALUES (gen_random_uuid(), :oid, NULL, :kid, '/query', 'POST', 500, "
                "120.5, 100, 0.0002, NOW() - INTERVAL '2 hours')"
            ),
            {"oid": UUID(org["organization_id"]), "kid": UUID(key_id)},
        )
        await session.commit()
    finally:
        await session.close()

    usage = await async_client.get(
        f"/api/v1/organizations/api-keys/{key_id}/usage", headers=h
    )
    assert usage.status_code == 200, usage.text
    u = usage.json()
    assert u["requests"] == 10
    assert u["errors"] == 1
    assert u["tokens"] == 550
    assert u["cost"] == pytest.approx(0.0011)
    assert u["p95_ms"] == pytest.approx(900.0, abs=1.0)


@pytest.mark.asyncio
async def test_api_key_forced_expiry_policy(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "KeysPolicy Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/organizations/api-keys", headers=h, json={"name": "old-key"}
    )
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    key_id = created.json()["key_id"]

    # Envejecer la clave (creada hace 3 días).
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE api_keys SET created_at = NOW() - INTERVAL '3 days' WHERE id = :kid"),
            {"kid": UUID(key_id)},
        )
        await session.commit()
    finally:
        await session.close()

    # Política: max 1 día → la clave queda rechazada en auth.
    policy = await async_client.put(
        "/api/v1/auth/sso/key-policy",
        headers=h,
        json={"max_age_days": 1},
    )
    assert policy.status_code == 200, policy.text

    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService, TokenValidationError

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    with pytest.raises(TokenValidationError):
        await billing.validate_token(token)

    # Sin política, la clave vuelve a funcionar.
    await async_client.put("/api/v1/auth/sso/key-policy", headers=h, json={"max_age_days": None})
    ctx = await billing.validate_token(token)
    assert ctx.organization_id == UUID(org["organization_id"])


# ---------------------------------------------------------------------------
# SCIM 2.0
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scim_users_and_groups(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Scim Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    # Generar token SCIM.
    tok = await async_client.post("/api/v1/auth/sso/scim-token", headers=h, json={})
    assert tok.status_code == 200, tok.text
    scim_token = tok.json()["token"]
    sh = _scim_headers(org["organization_id"], scim_token)

    # Auth falla con token malo.
    bad = await async_client.post(
        "/api/v1/scim/v2/Users",
        headers=_scim_headers(org["organization_id"], "wrong"),
        json={"userName": "x@example.com"},
    )
    assert bad.status_code == 401

    # Crear grupo (mapping a rol admin).
    group = await async_client.post(
        "/api/v1/scim/v2/Groups",
        headers=sh,
        json={"displayName": "admins", "role": "admin", "members": []},
    )
    assert group.status_code == 201, group.text
    gid = group.json()["id"]

    scim_email = f"ana-{uuid4().hex[:8]}@example.com"
    # Crear usuario.
    user = await async_client.post(
        "/api/v1/scim/v2/Users",
        headers=sh,
        json={
            "userName": scim_email,
            "externalId": "ext-ana-1",
            "displayName": "Ana Pérez",
            "active": True,
        },
    )
    assert user.status_code == 201, user.text
    uid = user.json()["id"]
    assert user.json()["userName"] == scim_email

    # Listar con filtro userName eq.
    listed = await async_client.get(
        f"/api/v1/scim/v2/Users?filter=userName%20eq%20%22{scim_email}%22",
        headers=sh,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["totalResults"] == 1

    # PATCH: cambiar rol vía group membership (PATCH group members add).
    patch = await async_client.patch(
        f"/api/v1/scim/v2/Groups/{gid}",
        headers=sh,
        json={
            "Operations": [
                {"op": "add", "path": "members", "value": [{"value": "ext-ana-1"}]}
            ]
        },
    )
    assert patch.status_code == 200, patch.text

    # El usuario quedó con rol admin (mapping del grupo).
    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

    roles = await PostgresMembershipRepository().get_user_roles(
        UUID(uid), UUID(org["organization_id"])
    )
    assert any(r.name == "admin" for r in roles), roles

    # DELETE user → sin membresías (provisionado fuera).
    deleted = await async_client.delete(f"/api/v1/scim/v2/Users/{uid}", headers=sh)
    assert deleted.status_code == 204, deleted.text
    roles2 = await PostgresMembershipRepository().get_user_roles(
        UUID(uid), UUID(org["organization_id"])
    )
    assert roles2 == []


# ---------------------------------------------------------------------------
# SSO OIDC
# ---------------------------------------------------------------------------
def _make_idp_keys() -> tuple[dict, dict]:
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = private.public_key()
    pub_nums = pub.public_numbers()
    pub_bytes = pub.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    jwk = {
        "kty": "RSA",
        "kid": "test-kid-1",
        "use": "sig",
        "alg": "RS256",
        "n": base64.urlsafe_b64encode(pub_nums.n.to_bytes((pub_nums.n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode(),
        "e": base64.urlsafe_b64encode(pub_nums.e.to_bytes((pub_nums.e.bit_length() + 7) // 8, "big")).rstrip(b"=").decode(),
    }
    priv_pem = private.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    )
    return jwk, {"pem": priv_pem.decode(), "pub": pub_bytes.decode()}


async def _configure_sso(async_client: AsyncClient, org: dict, issuer: str, client_id: str) -> None:
    h = _headers(org)
    cfg = await async_client.put(
        "/api/v1/auth/sso/config",
        headers=h,
        json={
            "enabled": True,
            "issuer": issuer,
            "client_id": client_id,
            "client_secret": "test-secret-123",
            "roles_claim": "roles",
        },
    )
    assert cfg.status_code == 200, cfg.text


@pytest.mark.asyncio
async def test_sso_start_redirects(async_client: AsyncClient, monkeypatch) -> None:
    import src.platform.enterprise.sso as sso_mod

    async def _fake_discover(iss: str) -> dict:
        return {
            "issuer": iss,
            "authorization_endpoint": "https://idp.example.test/auth",
            "token_endpoint": "https://idp.example.test/token",
            "jwks_uri": "https://idp.example.test/jwks",
        }

    monkeypatch.setattr(sso_mod, "_oidc_discover", _fake_discover)

    org = await _create_org(async_client, "Sso Org")
    org["session"] = await _owner_session(org["organization_id"])
    await _configure_sso(async_client, org, "https://idp.example.test/issuer", "client-x")

    start = await async_client.get(
        f"/api/v1/auth/sso/{org['organization_id']}/start",
        follow_redirects=False,
    )
    assert start.status_code == 302, start.text
    location = start.headers["location"]
    assert location.startswith("https://idp.example.test/auth")
    assert "response_type=code" in location
    assert "client_id=client-x" in location
    assert "nonce=" in location
    assert "state=" in location


@pytest.mark.asyncio
async def test_sso_callback_full_flow(async_client: AsyncClient, monkeypatch) -> None:

    org = await _create_org(async_client, "Sso Flow Org")
    org["session"] = await _owner_session(org["organization_id"])
    issuer = "https://idp.example.test/issuer"
    client_id = "client-flow"
    await _configure_sso(async_client, org, issuer, client_id)

    jwk, keys = _make_idp_keys()

    # Discovery + token + JWKS falsos.
    async def _fake_discover(iss: str) -> dict:
        return {
            "issuer": iss,
            "authorization_endpoint": "https://idp.example.test/auth",
            "token_endpoint": "https://idp.example.test/token",
            "jwks_uri": "https://idp.example.test/jwks",
        }

    async def _fake_exchange(token_endpoint: str, cid: str, secret: str, code: str, redirect: str) -> dict:
        nonce_from_code = code.split(":")[1]
        claims = {
            "iss": issuer,
            "aud": client_id,
            "sub": "sub-12345",
            "email": f"sso.{uuid4().hex[:8]}@example.com",
            "roles": ["engineers"],
            "nonce": nonce_from_code,
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        id_token = jwt.encode(claims, keys["pem"], algorithm="RS256", headers={"kid": "test-kid-1"})
        return {"id_token": id_token, "access_token": "at-123"}

    async def _fake_jwks(uri: str) -> list[dict]:
        return [jwk]

    import src.platform.enterprise.sso as sso_mod

    monkeypatch.setattr(sso_mod, "_oidc_discover", _fake_discover)
    monkeypatch.setattr(sso_mod, "_oidc_exchange_code", _fake_exchange)
    monkeypatch.setattr(sso_mod, "_fetch_jwks", _fake_jwks)

    # Crear un grupo SCIM "engineers" → rol developer (para probar el mapeo de roles).
    tok = await async_client.post("/api/v1/auth/sso/scim-token", headers=_headers(org), json={})
    scim_token = tok.json()["token"]
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO scim_groups (id, organization_id, display_name, role_name, members) "
                "VALUES (gen_random_uuid(), :oid, 'engineers', 'developer', '[]'::jsonb)"
            ),
            {"oid": UUID(org["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    # state = firmado con la org real; nonce dentro del code.
    from src.platform.enterprise.sso import _sign_state

    nonce = "test-nonce-abc"
    state = _sign_state(UUID(org["organization_id"]), nonce)
    cb = await async_client.get(
        f"/api/v1/auth/sso/callback?code=abc:{nonce}&state={state}&format=json",
        follow_redirects=False,
    )
    assert cb.status_code == 200, cb.text
    body = cb.json()
    assert body["email"].endswith("@example.com")
    assert body["organization_id"] == org["organization_id"]

    # El usuario se creó con rol developer (mapeo del grupo engineers).
    from src.infrastructure.postgres.relational_db import PostgresUserRepository

    user = await PostgresUserRepository().get_by_email(body["email"])
    assert user is not None
    assert str(user.organization_id) == org["organization_id"]
    from src.infrastructure.postgres.relational_db import PostgresMembershipRepository

    roles = await PostgresMembershipRepository().get_user_roles(
        user.id, UUID(org["organization_id"])
    )
    assert any(r.name == "developer" for r in roles), roles

    # El token de sesión funciona.
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    billing = BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())
    ctx = await billing.validate_token(body["access_token"])
    assert ctx.user_id == user.id


@pytest.mark.asyncio
async def test_sso_bad_state_rejected(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Sso Bad Org")
    org["session"] = await _owner_session(org["organization_id"])
    await _configure_sso(async_client, org, "https://idp.example.test/issuer", "client-x")

    cb = await async_client.get(
        "/api/v1/auth/sso/callback?code=abc&state=forged-state",
        follow_redirects=False,
    )
    assert cb.status_code == 400, cb.text
    assert cb.json()["error"] == "invalid_state"


# ---------------------------------------------------------------------------
# Self-serve billing upgrade
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_self_serve_upgrade(async_client: AsyncClient, monkeypatch) -> None:
    from src.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "SELF_SERVICE_UPGRADE_ENABLED", True)

    org = await _create_org(async_client, "Upgrade Org")
    org["session"] = await _owner_session(org["organization_id"])
    h = _headers(org)

    resp = await async_client.post(
        "/api/v1/billing/subscription/upgrade",
        headers={**h, "X-New-Plan": "pro"},
    )
    assert resp.status_code == 200, resp.text

    sub = await async_client.get("/api/v1/billing/subscription", headers=h)
    assert sub.status_code == 200, sub.text
    assert sub.json()["plan_name"] == "pro"

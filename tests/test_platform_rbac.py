# =============================================================================
# Platform RBAC — roles granulares del Control Center
# =============================================================================
# super_admin / platform_admin pasan todo; los demás roles exigen el permiso
# exacto. Prueba allow/deny, cross-permiso, read_only, aislamiento de
# endpoints nuevos y unit de authorize().
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.auth.passwords import hash_password


async def _seed_platform_user(
    email: str, password: str, role_name: str
) -> UUID:
    """Crea (o actualiza) un usuario de plataforma con un rol platform."""
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import (
        ensure_platform_admin_schema,
    )
    from src.infrastructure.postgres.session import get_async_session

    await ensure_platform_admin_schema()
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text("SELECT id FROM users WHERE lower(email) = lower(:email)"),
                {"email": email},
            )
        ).fetchone()
        if existing:
            user_id = existing.id
            await session.execute(
                text(
                    "UPDATE users SET is_platform_admin = true, "
                    "password_hash = :ph WHERE id = :id"
                ),
                {"ph": hash_password(password), "id": user_id},
            )
        else:
            result = await session.execute(
                text(
                    "INSERT INTO users (id, organization_id, external_id, email_hash, "
                    "role, email, password_hash, is_platform_admin) "
                    "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', "
                    ":email, :ph, true) RETURNING id"
                ),
                {
                    "ext": f"platform-{uuid4().hex[:12]}",
                    "eh": __import__("hashlib").sha256(email.encode()).hexdigest(),
                    "email": email,
                    "ph": hash_password(password),
                },
            )
            user_id = result.fetchone().id
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT :uid, id FROM platform_roles WHERE name = :role "
                "ON CONFLICT DO NOTHING"
            ),
            {"uid": user_id, "role": role_name},
        )
        await session.commit()
        return user_id
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _platform_login(client: AsyncClient, email: str, password: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _trial(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"RBAC Co {uuid4().hex[:8]}",
            "email": f"rbac-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_super_admin_passes_all_platform_routes(
    async_client: AsyncClient,
) -> None:
    email = f"super-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "super_admin")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    for path in (
        "/api/v1/platform/metrics",
        "/api/v1/platform/organizations",
        "/api/v1/platform/subscriptions",
        "/api/v1/platform/roles",
        "/api/v1/platform/users",
        "/api/v1/platform/audit",
        "/api/v1/platform/operations",
        "/api/v1/platform/settings",
        "/api/v1/platform/notifications",
    ):
        resp = await async_client.get(path, headers=h)
        assert resp.status_code == 200, (path, resp.status_code, resp.text)


@pytest.mark.asyncio
async def test_read_only_can_view_but_not_mutate(
    async_client: AsyncClient,
) -> None:
    email = f"ro-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "read_only")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    ok = await async_client.get("/api/v1/platform/organizations", headers=h)
    assert ok.status_code == 200, ok.text
    metrics = await async_client.get("/api/v1/platform/metrics", headers=h)
    assert metrics.status_code == 200, metrics.text

    for path in (
        "/api/v1/platform/users",
        "/api/v1/platform/roles",
        "/api/v1/platform/audit",
        "/api/v1/platform/subscriptions",
        "/api/v1/platform/settings",
    ):
        resp = await async_client.get(path, headers=h)
        assert resp.status_code == 403, (path, resp.status_code)

    # Mutaciones: prohibidas sin el permiso exacto.
    orgs = (await async_client.get("/api/v1/platform/organizations", headers=h)).json()
    assert len(orgs["organizations"]) >= 0
    if len(orgs["organizations"]) > 0:
        oid = orgs["organizations"][0]["id"]
        resp = await async_client.post(
            f"/api/v1/platform/organizations/{oid}/suspend", headers=h
        )
        assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_finance_only_billing_and_analytics(
    async_client: AsyncClient,
) -> None:
    email = f"fin-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "finance")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    assert (await async_client.get("/api/v1/platform/subscriptions", headers=h)).status_code == 200
    assert (await async_client.get("/api/v1/platform/metrics", headers=h)).status_code == 200
    # Sin impersonate ni tenant.suspend: denegado por permiso, no por rol.
    assert (await async_client.get("/api/v1/platform/users", headers=h)).status_code == 403
    assert (await async_client.get("/api/v1/platform/audit", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_security_auditor_only_audit_and_tenants(
    async_client: AsyncClient,
) -> None:
    email = f"aud-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "security_auditor")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    assert (await async_client.get("/api/v1/platform/audit", headers=h)).status_code == 200
    assert (await async_client.get("/api/v1/platform/organizations", headers=h)).status_code == 200
    assert (await async_client.get("/api/v1/platform/subscriptions", headers=h)).status_code == 403
    assert (await async_client.get("/api/v1/platform/users", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_support_can_impersonate_but_not_manage_billing(
    async_client: AsyncClient,
) -> None:
    email = f"sup-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "support")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    org = await _trial(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{org['organization_id']}/impersonate",
        headers=h,
        json={"reason": "test"},
    )
    assert resp.status_code == 200, resp.text
    assert (await async_client.get("/api/v1/platform/subscriptions", headers=h)).status_code == 403


@pytest.mark.asyncio
async def test_operations_cannot_impersonate(
    async_client: AsyncClient,
) -> None:
    email = f"ops-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "operations")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    org = await _trial(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{org['organization_id']}/impersonate",
        headers=h,
        json={"reason": "test"},
    )
    assert resp.status_code == 403, resp.text
    assert (await async_client.get("/api/v1/platform/operations", headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_platform_routes_reject_tenant_sessions(
    async_client: AsyncClient,
) -> None:
    """Un owner de tenant (sesión portal) no accede a /platform/*."""
    org = await _trial(async_client)
    org["session"] = None
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert user is not None
    h = {
        "Authorization": f"Bearer {encrypt_session(user.id, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
    }
    resp = await async_client.get("/api/v1/platform/organizations", headers=h)
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_tenant_360_endpoints_work_for_super_admin(
    async_client: AsyncClient,
) -> None:
    email = f"t360-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "super_admin")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    org = await _trial(async_client)
    oid = org["organization_id"]

    for suffix in ("users", "agents", "sources", "billing", "security", "audit"):
        resp = await async_client.get(f"/api/v1/platform/organizations/{oid}/{suffix}", headers=h)
        assert resp.status_code == 200, (suffix, resp.status_code, resp.text)

    health = await async_client.get(f"/api/v1/platform/tenants/{oid}/health", headers=h)
    assert health.status_code == 200, health.text
    body = health.json()
    assert 0 <= body["score"] <= 100
    assert body["label"] in ("HEALTHY", "WATCH", "AT_RISK")

    missing = await async_client.get(
        "/api/v1/platform/organizations/ffffffff-ffff-ffff-ffff-ffffffffffff/users",
        headers=h,
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_tenant_360_requires_tenant_read(
    async_client: AsyncClient,
) -> None:
    email = f"no360-{uuid4().hex[:8]}@example.com"
    await _seed_platform_user(email, "secret-123", "security_auditor")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    org = await _trial(async_client)
    resp = await async_client.get(
        f"/api/v1/platform/organizations/{org['organization_id']}/billing", headers=h
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_new_tenant_roles_assignable_via_api(
    async_client: AsyncClient,
) -> None:
    """Los roles nuevos (ai_engineer, developer, analyst, billing, data_engineer)
    son asignables por owner y respetan el RBAC resultante."""
    org = await _trial(async_client)
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    owner = await PostgresUserRepository().get_by_external_id(
        UUID(org["organization_id"]), "default-admin"
    )
    assert owner is not None
    h = {
        "Authorization": f"Bearer {encrypt_session(owner.id, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
    }

    # Invitar con rol nuevo.
    invited_email = f"ai-{uuid4().hex[:8]}@example.com"
    invite = await async_client.post(
        "/api/v1/organizations/invites",
        headers=h,
        json={"email": invited_email, "role": "ai_engineer"},
    )
    assert invite.status_code == 201, invite.text

    # Rol desconocido → 400.
    bad = await async_client.post(
        "/api/v1/organizations/invites",
        headers=h,
        json={"email": f"x-{uuid4().hex[:8]}@example.com", "role": "not_a_role"},
    )
    assert bad.status_code == 400, bad.text

    # Crear el usuario invitado (miembro admin de la org: el accept exige
    # org:read + que el autenticado sea el email invitado) y aceptar con su sesión.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash) "
                "VALUES (gen_random_uuid(), :oid, :ext, :eh, 'member', "
                ":email, :ph) RETURNING id"
            ),
            {
                "oid": UUID(org["organization_id"]),
                "ext": f"inv-{uuid4().hex[:12]}",
                "eh": __import__("hashlib").sha256(invited_email.encode()).hexdigest(),
                "email": invited_email,
                "ph": hash_password("secret-123"),
            },
        )
        invited_user_id = result.fetchone().id
        await session.execute(
            text(
                "INSERT INTO memberships (organization_id, user_id, role_id) "
                "SELECT :oid, :uid, id FROM roles WHERE organization_id IS NULL AND name = 'admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"oid": UUID(org["organization_id"]), "uid": invited_user_id},
        )
        await session.commit()
    finally:
        await session.close()

    invited_headers = {
        "Authorization": f"Bearer {encrypt_session(invited_user_id, UUID(org['organization_id']))}",
        "X-Organization-Id": org["organization_id"],
    }
    token = invite.json()["token"]
    accepted = await async_client.post(
        f"/api/v1/organizations/invites/{invite.json()['id']}/accept",
        headers=invited_headers,
        json={"token": token},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role"] == "ai_engineer"


# ---------------------------------------------------------------------------
# Unit — authorize()
# ---------------------------------------------------------------------------


class TestAuthorize:
    def test_authorize_allows_with_permission(self) -> None:
        from src.core.domain.entities import TenantContext
        from src.platform.rbac.authorization import authorize

        ctx = TenantContext(
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            permissions=frozenset({"tenant.read", "billing.read"}),
            auth_type="platform_session",
        )
        assert authorize(ctx, "tenant.read") is ctx

    def test_authorize_denies_without_permission(self) -> None:
        from src.core.domain.entities import TenantContext
        from src.platform.rbac.authorization import (
            AuthorizationError,
            authorize,
        )

        ctx = TenantContext(
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=None,
            permissions=frozenset({"tenant.read"}),
            auth_type="platform_session",
        )
        with pytest.raises(AuthorizationError):
            authorize(ctx, "tenant.suspend")

    def test_authorize_admin_star_passes(self) -> None:
        from src.core.domain.entities import TenantContext
        from src.platform.rbac.authorization import authorize

        ctx = TenantContext(
            tenant_id=None,
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            permissions=frozenset(),
            scopes=frozenset({"admin:*"}),
            auth_type="platform_session",
        )
        assert authorize(ctx, "tenant.suspend") is ctx

    def test_authorize_rejects_cross_tenant(self) -> None:
        from src.core.domain.entities import TenantContext
        from src.platform.rbac.authorization import (
            AuthorizationError,
            authorize,
        )

        ctx = TenantContext(
            tenant_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=None,
            permissions=frozenset({"tenant.read"}),
            auth_type="api_token",
        )
        with pytest.raises(AuthorizationError):
            authorize(
                ctx,
                "tenant.read",
                tenant_id=UUID("00000000-0000-0000-0000-000000000099"),
            )

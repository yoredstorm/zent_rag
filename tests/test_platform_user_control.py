# =============================================================================
# Control Center — control total de usuarios (plataforma y tenant)
# =============================================================================
# Crear/desactivar/activar usuarios de plataforma, suspender/reactivar usuarios
# de tenant, cerrar sesiones, reset de contraseña y edición de email, todo con
# auditoría obligatoria. La suspensión mata las sesiones vivas (marcador por
# usuario) y bloquea el login hasta reactivar.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.auth.passwords import hash_password


async def _seed_platform_user(email: str, password: str, role_name: str) -> UUID:
    """Crea un usuario de plataforma con rol platform (patrón test_platform_rbac)."""
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import (
        ensure_platform_admin_schema,
    )
    from src.infrastructure.postgres.session import get_async_session

    await ensure_platform_admin_schema()
    session = await get_async_session()
    try:
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


async def _admin(client: AsyncClient) -> tuple[dict, str]:
    """(headers de super_admin, user_id) frescos."""
    email = f"cc-admin-{uuid4().hex[:8]}@example.com"
    uid = await _seed_platform_user(email, "secret-123", "super_admin")
    token = (await _platform_login(client, email, "secret-123"))["access_token"]
    return _headers(token), str(uid)


async def _signup(client: AsyncClient, password: str = "s3cret-pass-123") -> dict:
    """Organización nueva con owner (email+password) y sesión portal."""
    email = f"tenant-{uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/signup",
        json={
            "company_name": f"Tenant Co {uuid4().hex[:6]}",
            "email": email,
            "password": password,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    data["owner_email"] = email
    data["owner_password"] = password
    return data


async def _me(client: AsyncClient, token: str) -> tuple[int, dict]:
    resp = await client.get("/api/v1/auth/me", headers=_headers(token))
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {}
    return resp.status_code, body


@pytest.mark.asyncio
async def test_create_platform_user_and_login_with_reset_token(
    async_client: AsyncClient,
) -> None:
    admin_h, _ = await _admin(async_client)
    email = f"cc-new-{uuid4().hex[:8]}@example.com"

    resp = await async_client.post(
        "/api/v1/platform/users",
        headers=admin_h,
        json={"email": email, "role_name": "read_only"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["reset_token"]
    assert data["email"] == email

    # Duplicado y rol inválido.
    dup = await async_client.post(
        "/api/v1/platform/users",
        headers=admin_h,
        json={"email": email, "role_name": "read_only"},
    )
    assert dup.status_code == 409, dup.text
    bad = await async_client.post(
        "/api/v1/platform/users",
        headers=admin_h,
        json={"email": f"cc-bad-{uuid4().hex[:8]}@example.com", "role_name": "nope_rol"},
    )
    assert bad.status_code == 404, bad.text

    # Sin password aún: se define con el reset token y ya puede entrar.
    reset = await async_client.post(
        "/api/v1/auth/reset-password",
        json={"token": data["reset_token"], "password": "Newpass-123"},
    )
    assert reset.status_code == 200, reset.text
    token = (await _platform_login(async_client, email, "Newpass-123"))["access_token"]

    assert (
        await async_client.get("/api/v1/platform/organizations", headers=_headers(token))
    ).status_code == 200
    assert (
        await async_client.get("/api/v1/platform/users", headers=_headers(token))
    ).status_code == 403
    deny = await async_client.post(
        "/api/v1/platform/users",
        headers=_headers(token),
        json={"email": f"cc-x-{uuid4().hex[:8]}@example.com", "role_name": "read_only"},
    )
    assert deny.status_code == 403, deny.text


@pytest.mark.asyncio
async def test_platform_role_assign_revoke_effective_immediately(
    async_client: AsyncClient,
) -> None:
    admin_h, _ = await _admin(async_client)
    email = f"cc-ro-{uuid4().hex[:8]}@example.com"
    uid = await _seed_platform_user(email, "secret-123", "read_only")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    h = _headers(token)

    assert (
        await async_client.get("/api/v1/platform/operations", headers=h)
    ).status_code == 403

    assign = await async_client.post(
        f"/api/v1/platform/users/{uid}/roles",
        headers=admin_h,
        json={"role_name": "operations", "action": "assign"},
    )
    assert assign.status_code == 200, assign.text
    assert (
        await async_client.get("/api/v1/platform/operations", headers=h)
    ).status_code == 200

    revoke = await async_client.post(
        f"/api/v1/platform/users/{uid}/roles",
        headers=admin_h,
        json={"role_name": "operations", "action": "revoke"},
    )
    assert revoke.status_code == 200, revoke.text
    assert (
        await async_client.get("/api/v1/platform/operations", headers=h)
    ).status_code == 403

    # Rol inexistente: 404 (y no debe activar el flag del usuario).
    missing = await async_client.post(
        f"/api/v1/platform/users/{uid}/roles",
        headers=admin_h,
        json={"role_name": "rol_fantasma", "action": "assign"},
    )
    assert missing.status_code == 404, missing.text


@pytest.mark.asyncio
async def test_deactivate_platform_user_kills_sessions_and_blocks_login(
    async_client: AsyncClient,
) -> None:
    admin_h, admin_uid = await _admin(async_client)
    email = f"cc-susp-{uuid4().hex[:8]}@example.com"
    uid = await _seed_platform_user(email, "secret-123", "read_only")
    token = (await _platform_login(async_client, email, "secret-123"))["access_token"]

    assert (
        await async_client.get("/api/v1/platform/organizations", headers=_headers(token))
    ).status_code == 200

    deact = await async_client.post(
        f"/api/v1/platform/users/{uid}/deactivate", headers=admin_h
    )
    assert deact.status_code == 200, deact.text

    # Sesión viva muere al instante.
    gone = await async_client.get(
        "/api/v1/platform/organizations", headers=_headers(token)
    )
    assert gone.status_code == 401, gone.text
    assert gone.json().get("error_code") == "session_revoked"

    # Login bloqueado mientras está desactivado.
    blocked = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": "secret-123"},
    )
    assert blocked.status_code == 403, blocked.text
    b = blocked.json()
    code = b.get("error_code") or (b.get("detail") or {}).get("error_code")
    assert code == "user_suspended", b

    # No puede desactivarse a sí mismo.
    self_off = await async_client.post(
        f"/api/v1/platform/users/{admin_uid}/deactivate", headers=admin_h
    )
    assert self_off.status_code == 400, self_off.text

    # Reactivar devuelve el acceso.
    activate = await async_client.post(
        f"/api/v1/platform/users/{uid}/activate", headers=admin_h
    )
    assert activate.status_code == 200, activate.text
    token2 = (await _platform_login(async_client, email, "secret-123"))["access_token"]
    assert (
        await async_client.get("/api/v1/platform/organizations", headers=_headers(token2))
    ).status_code == 200


@pytest.mark.asyncio
async def test_suspend_tenant_user_kills_sessions_and_blocks_login(
    async_client: AsyncClient,
) -> None:
    org = await _signup(async_client)
    oid = org["organization_id"]
    token = org["access_token"]
    code, me = await _me(async_client, token)
    assert code == 200 and me["user_id"]
    uid = me["user_id"]

    admin_h, _ = await _admin(async_client)
    susp = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/users/{uid}/suspend", headers=admin_h
    )
    assert susp.status_code == 200, susp.text

    gone = await async_client.get("/api/v1/auth/me", headers=_headers(token))
    assert gone.status_code == 401, gone.text

    blocked = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": org["owner_password"]},
    )
    assert blocked.status_code == 403, blocked.text
    b = blocked.json()
    code = b.get("error_code") or (b.get("detail") or {}).get("error_code")
    assert code == "user_suspended", b

    # Auditoría obligatoria de la suspensión.
    audit = await async_client.get(
        "/api/v1/platform/audit?action=platform.user_suspended", headers=admin_h
    )
    assert audit.status_code == 200, audit.text
    assert uid in audit.text

    activate = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/users/{uid}/activate", headers=admin_h
    )
    assert activate.status_code == 200, activate.text
    ok = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": org["owner_password"]},
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_revoke_sessions_forces_relogin(async_client: AsyncClient) -> None:
    org = await _signup(async_client)
    oid = org["organization_id"]
    token = org["access_token"]
    uid = (await _me(async_client, token))[1]["user_id"]

    admin_h, _ = await _admin(async_client)
    rev = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/users/{uid}/revoke-sessions",
        headers=admin_h,
    )
    assert rev.status_code == 200, rev.text

    gone = await async_client.get("/api/v1/auth/me", headers=_headers(token))
    assert gone.status_code == 401, gone.text

    # No está suspendido: puede volver a entrar.
    again = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": org["owner_password"]},
    )
    assert again.status_code == 200, again.text


@pytest.mark.asyncio
async def test_password_reset_revokes_sessions_and_changes_password(
    async_client: AsyncClient,
) -> None:
    org = await _signup(async_client)
    oid = org["organization_id"]
    token = org["access_token"]
    uid = (await _me(async_client, token))[1]["user_id"]

    admin_h, _ = await _admin(async_client)
    reset = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/users/{uid}/password-reset",
        headers=admin_h,
    )
    assert reset.status_code == 200, reset.text
    reset_token = reset.json()["reset_token"]
    assert reset.json()["email_sent"] is False  # SMTP no configurado en test

    apply = await async_client.post(
        "/api/v1/auth/reset-password",
        json={"token": reset_token, "password": "Brandnew-123"},
    )
    assert apply.status_code == 200, apply.text

    # Aplicar el reset mata las sesiones vivas.
    gone = await async_client.get("/api/v1/auth/me", headers=_headers(token))
    assert gone.status_code == 401, gone.text

    new_ok = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": "Brandnew-123"},
    )
    assert new_ok.status_code == 200, new_ok.text
    old_no = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": org["owner_password"]},
    )
    assert old_no.status_code == 401, old_no.text


@pytest.mark.asyncio
async def test_edit_tenant_user_email(async_client: AsyncClient) -> None:
    org = await _signup(async_client)
    oid = org["organization_id"]
    token = org["access_token"]
    uid = (await _me(async_client, token))[1]["user_id"]

    other = await _signup(async_client)  # email ya en uso, otra organización

    admin_h, _ = await _admin(async_client)
    conflict = await async_client.patch(
        f"/api/v1/platform/organizations/{oid}/users/{uid}",
        headers=admin_h,
        json={"email": other["owner_email"]},
    )
    assert conflict.status_code == 409, conflict.text

    new_email = f"tenant-new-{uuid4().hex[:8]}@example.com"
    ok = await async_client.patch(
        f"/api/v1/platform/organizations/{oid}/users/{uid}",
        headers=admin_h,
        json={"email": new_email},
    )
    assert ok.status_code == 200, ok.text

    old_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": org["owner_email"], "password": org["owner_password"]},
    )
    assert old_login.status_code == 401, old_login.text
    new_login = await async_client.post(
        "/api/v1/auth/login",
        json={"email": new_email, "password": org["owner_password"]},
    )
    assert new_login.status_code == 200, new_login.text


@pytest.mark.asyncio
async def test_impersonate_specific_user(async_client: AsyncClient) -> None:
    org = await _signup(async_client)
    oid = org["organization_id"]
    uid = (await _me(async_client, org["access_token"]))[1]["user_id"]

    admin_h, admin_uid = await _admin(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/impersonate",
        headers=admin_h,
        json={"reason": "soporte usuario puntual", "user_id": uid},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    from src.platform.auth.session import decrypt_session

    payload = decrypt_session(token)
    assert str(payload.user_id) == uid
    assert payload.typ == "portal"
    assert str(payload.imp_by) == admin_uid

    code, me = await _me(async_client, token)
    assert code == 200
    assert me["user_id"] == uid

    # Usuario que no pertenece a la organización: 404.
    stranger = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/impersonate",
        headers=admin_h,
        json={"reason": "soporte usuario puntual", "user_id": str(uuid4())},
    )
    assert stranger.status_code == 404, stranger.text


@pytest.mark.asyncio
async def test_user_session_revocation_unit() -> None:
    from src.platform.auth.session import (
        decrypt_session,
        encrypt_session,
        revoke_user_sessions,
        session_is_active,
    )

    uid = uuid4()
    oid = uuid4()
    token = encrypt_session(uid, oid)
    payload = decrypt_session(token)
    assert (
        await session_is_active(
            payload.sid, user_id=uid, issued_at=payload.issued_at
        )
        is True
    )

    await revoke_user_sessions(uid)
    assert (
        await session_is_active(
            payload.sid, user_id=uid, issued_at=payload.issued_at
        )
        is False
    )

    # Token emitido después del marcador sigue vivo (reactivación).
    fresh = decrypt_session(encrypt_session(uid, oid))
    assert (
        await session_is_active(fresh.sid, user_id=uid, issued_at=fresh.issued_at)
        is True
    )

    # Token legacy (sin iat) queda revocado por el marcador.
    assert await session_is_active(None, user_id=uid, issued_at=0) is False

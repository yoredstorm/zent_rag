# =============================================================================
# Control Center — acciones sobre clientes (rutas HTTP)
# =============================================================================
# Contrato nuevo: deletion-preview, DELETE con confirmación tipada y guarda
# de platform admin, set directo de contraseña, PATCH de contacto, asignación
# de plan y export JSON. Complementa tests/test_tenant_purge.py (servicio).
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.auth.passwords import hash_password, verify_password

_OWNER_ROLE_ID = "50000000-0000-0000-0000-000000000001"


async def _platform_admin(client: AsyncClient, email: str, role: str = "super_admin") -> dict[str, str]:
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
                "eh": hashlib.sha256(email.encode()).hexdigest(),
                "email": email,
                "ph": hash_password("secret-123"),
            },
        )
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT u.id, pr.id FROM users u CROSS JOIN platform_roles pr "
                "WHERE lower(u.email) = lower(:email) AND pr.name = :role "
                "ON CONFLICT DO NOTHING"
            ),
            {"email": email, "role": role},
        )
        await session.commit()
    finally:
        await session.close()
    login = await client.post("/api/v1/auth/platform/login", json={"email": email, "password": "secret-123"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _create_org_with_user(name: str) -> dict:
    org_id = uuid4()
    user_id = uuid4()
    email = f"cc-{uuid4().hex[:8]}@example.com"
    await PostgresOrganizationRepository().create_organization(org_id, name)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO users (id, organization_id, external_id, email_hash, "
                "role, email, password_hash, is_platform_admin) "
                "VALUES (:uid, :oid, :ext, :eh, 'owner', :email, 'x', false)"
            ),
            {
                "uid": user_id,
                "oid": org_id,
                "ext": f"cc-{uuid4().hex[:12]}",
                "eh": hashlib.sha256(email.encode()).hexdigest(),
                "email": email,
            },
        )
        await session.execute(
            text("INSERT INTO memberships (organization_id, user_id, role_id) VALUES (:oid, :uid, :rid)"),
            {"oid": org_id, "uid": user_id, "rid": UUID(_OWNER_ROLE_ID)},
        )
        await session.execute(
            text("INSERT INTO workspaces (organization_id, name, slug, kind) VALUES (:oid, :name, :slug, 'business')"),
            {"oid": org_id, "name": name, "slug": f"cc-{uuid4().hex[:10]}"},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {"org_id": org_id, "user_id": user_id, "email": email, "name": name}


async def _db_scalar(sql: str, params: dict):
    session = await get_async_session()
    try:
        return (await session.execute(text(sql), params)).scalar()
    finally:
        await session.close()


async def _db_execute(sql: str, params: dict) -> None:
    session = await get_async_session()
    try:
        await session.execute(text(sql), params)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_platform_tenant_actions_end_to_end(async_client: AsyncClient) -> None:
    org = await _create_org_with_user(f"CC Actions {uuid4().hex[:6]}")
    oid, uid = str(org["org_id"]), str(org["user_id"])
    plat = await _platform_admin(async_client, f"padmin-cc-{uuid4().hex[:8]}@zent.example")

    # Preview del impacto.
    preview = await async_client.get(f"/api/v1/platform/organizations/{oid}/deletion-preview", headers=plat)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["organization"]["id"] == oid
    assert body["organization"]["protected"] is False
    assert body["users"] == 1
    assert body["memberships"] == 1
    assert body["total_rows"] > 0

    # Contacto de la organización.
    patch = await async_client.patch(
        f"/api/v1/platform/organizations/{oid}",
        headers=plat,
        json={"company_name": "CC Actions SAC", "email": "cc-actions@example.com"},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["company_name"] == "CC Actions SAC"

    # Contraseña directa (sin email) con revocación de sesiones.
    pw = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/users/{uid}/password",
        headers=plat,
        json={"password": "nueva-clave-123", "revoke_sessions": True},
    )
    assert pw.status_code == 200, pw.text
    stored = await _db_scalar("SELECT password_hash FROM users WHERE id = :uid", {"uid": UUID(uid)})
    assert verify_password("nueva-clave-123", stored)

    # Asignación de plan (el catálogo se siembra por migraciones).
    plan_name = await _db_scalar("SELECT name FROM plans ORDER BY price_monthly_cents DESC, name LIMIT 1", {})
    assert plan_name, "el catálogo de planes debe estar sembrado"
    plan = await async_client.post(
        f"/api/v1/platform/organizations/{oid}/plan",
        headers=plat,
        json={"plan_name": plan_name, "billing_interval": "monthly"},
    )
    assert plan.status_code == 200, plan.text
    plan_body = plan.json()
    assert plan_body["plan_name"] == plan_name
    assert plan_body["assigned"] is True

    # Export JSON de la ficha.
    export = await async_client.get(f"/api/v1/platform/organizations/{oid}/export", headers=plat)
    assert export.status_code == 200, export.text
    data = export.json()
    assert data["organization"]["id"] == oid
    assert [u["id"] for u in data["users"]] == [uid]
    assert data["counts"]["workspaces"] == 1
    assert data["subscription"] is not None

    # Confirmación tipada obligatoria.
    bad = await async_client.request(
        "DELETE",
        f"/api/v1/platform/organizations/{oid}",
        headers=plat,
        json={"confirmation": "otra-cosa"},
    )
    assert bad.status_code == 400, bad.text
    assert bad.json()["error_code"] == "confirmation_mismatch"

    # Guarda: la org con un platform admin como miembro no se elimina.
    await _db_execute(
        "UPDATE users SET is_platform_admin = true WHERE id = :uid",
        {"uid": UUID(uid)},
    )
    try:
        guarded = await async_client.request(
            "DELETE",
            f"/api/v1/platform/organizations/{oid}",
            headers=plat,
            json={"confirmation": "CC Actions SAC"},
        )
        assert guarded.status_code == 409, guarded.text
        assert guarded.json()["error_code"] == "protected_tenant"
    finally:
        await _db_execute(
            "UPDATE users SET is_platform_admin = false WHERE id = :uid",
            {"uid": UUID(uid)},
        )

    # Eliminación real: cero huérfanos y org fuera.
    deleted = await async_client.request(
        "DELETE",
        f"/api/v1/platform/organizations/{oid}",
        headers=plat,
        json={"confirmation": "CC Actions SAC"},
    )
    assert deleted.status_code == 200, deleted.text
    result = deleted.json()
    assert result["after"]["total_rows"] == 0
    assert result["verification"]["org_rows"] == 0
    assert result["verification"]["user_refs"] == 0
    assert result["verification"]["org_refs"] == 0
    assert await PostgresOrganizationRepository().get_by_id(org["org_id"]) is None

    again = await async_client.request(
        "DELETE",
        f"/api/v1/platform/organizations/{oid}",
        headers=plat,
        json={"confirmation": "CC Actions SAC"},
    )
    assert again.status_code == 404


@pytest.mark.asyncio
async def test_platform_tenant_delete_requires_permission(async_client: AsyncClient) -> None:
    org = await _create_org_with_user(f"CC Perms {uuid4().hex[:6]}")
    oid = str(org["org_id"])
    support = await _platform_admin(async_client, f"padmin-support-{uuid4().hex[:8]}@zent.example", role="support")
    try:
        preview = await async_client.get(f"/api/v1/platform/organizations/{oid}/deletion-preview", headers=support)
        assert preview.status_code == 403, preview.text
        assert preview.json()["error_code"] == "platform_permission_denied"

        delete = await async_client.request(
            "DELETE",
            f"/api/v1/platform/organizations/{oid}",
            headers=support,
            json={"confirmation": org["name"]},
        )
        assert delete.status_code == 403, delete.text
    finally:
        # El permiso denegado no debe haber tocado la org: se limpia con un
        # super admin.
        superuser = await _platform_admin(async_client, f"padmin-clean-{uuid4().hex[:8]}@zent.example")
        deleted = await async_client.request(
            "DELETE",
            f"/api/v1/platform/organizations/{oid}",
            headers=superuser,
            json={"confirmation": org["name"]},
        )
        assert deleted.status_code == 200, deleted.text
    assert await PostgresOrganizationRepository().get_by_id(org["org_id"]) is None

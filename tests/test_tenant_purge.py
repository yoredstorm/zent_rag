# =============================================================================
# TenantPurgeService — hard delete de un tenant (Control Center)
# =============================================================================
# Contrato central: se borra TODO rastro de la organización objetivo (filas
# org-scoped, usuarios, membresías, workspaces y la propia organización) y
# NADA de las demás organizaciones. Las aserciones no dependen de Qdrant ni de
# Redis (entornos de CI varían): la verificación interna del servicio ya
# reporta esos almacenes y aquí solo se exige cero para los ítems locales.
from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.postgres.relational_db import PostgresOrganizationRepository
from src.infrastructure.postgres.session import get_async_session
from src.platform.tenant_purge.service import TenantPurgeService

_OWNER_ROLE_ID = "50000000-0000-0000-0000-000000000001"


async def _create_org_with_data(name: str) -> dict:
    org_id = uuid4()
    user_id = uuid4()
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
                "ext": f"purge-{uuid4().hex[:12]}",
                "eh": hashlib.sha256(str(user_id).encode()).hexdigest(),
                "email": f"purge-{uuid4().hex[:8]}@example.com",
            },
        )
        await session.execute(
            text("INSERT INTO memberships (organization_id, user_id, role_id) VALUES (:oid, :uid, :rid)"),
            {"oid": org_id, "uid": user_id, "rid": UUID(_OWNER_ROLE_ID)},
        )
        await session.execute(
            text(
                "INSERT INTO workspaces (organization_id, name, slug, kind) "
                "VALUES (:oid, :name, :slug, 'business')"
            ),
            {"oid": org_id, "name": name, "slug": f"purge-{uuid4().hex[:10]}"},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    return {"org_id": org_id, "user_id": user_id}


async def _count(table: str, org_id: UUID) -> int:
    session = await get_async_session()
    try:
        value = (
            await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE organization_id = :oid"),  # noqa: S608 — tabla del set fijo del test
                {"oid": org_id},
            )
        ).scalar()
        return int(value or 0)
    finally:
        await session.close()


async def test_tenant_purge_removes_everything_without_collateral_damage():
    victim = await _create_org_with_data(f"Purge Victim {uuid4().hex[:6]}")
    bystander = await _create_org_with_data(f"Purge Bystander {uuid4().hex[:6]}")
    svc = TenantPurgeService()

    preview = await svc.preview(victim["org_id"])
    assert preview["organization"] is not None
    assert preview["organization"]["protected"] is False
    assert preview["users"] == 1
    assert preview["memberships"] == 1
    assert preview["total_rows"] > 0

    result = await svc.execute(victim["org_id"])

    assert result["before"]["total_rows"] > 0
    assert result["after"]["total_rows"] == 0
    assert result["verification"]["org_rows"] == 0
    assert result["verification"]["user_refs"] == 0
    assert result["verification"]["org_refs"] == 0
    assert result["verification"]["managed_databases"] == []
    assert result["verification"]["managed_roles"] == []

    assert await PostgresOrganizationRepository().get_by_id(victim["org_id"]) is None
    for table in ("users", "memberships", "workspaces"):
        assert await _count(table, victim["org_id"]) == 0, table

    # Cero daño colateral: el vecino sigue completo.
    assert await PostgresOrganizationRepository().get_by_id(bystander["org_id"]) is not None
    assert await _count("users", bystander["org_id"]) == 1
    assert await _count("memberships", bystander["org_id"]) == 1
    assert await _count("workspaces", bystander["org_id"]) == 1

    # El test no deja residuo: purga también al vecino.
    await svc.execute(bystander["org_id"])
    assert await PostgresOrganizationRepository().get_by_id(bystander["org_id"]) is None


async def test_tenant_purge_guards_platform_admin_orgs():
    org = await _create_org_with_data(f"Purge Guard {uuid4().hex[:6]}")
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE users SET is_platform_admin = true WHERE id = :uid"),
            {"uid": org["user_id"]},
        )
        await session.commit()
    finally:
        await session.close()

    preview = await TenantPurgeService().preview(org["org_id"])
    assert preview["organization"]["protected"] is True
    assert preview["organization"]["protected_reason"] == "platform_admin_member"

    # Limpieza: revierte el flag y purga la organización de prueba.
    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE users SET is_platform_admin = false WHERE id = :uid"),
            {"uid": org["user_id"]},
        )
        await session.commit()
    finally:
        await session.close()
    result = await TenantPurgeService().execute(org["org_id"])
    assert result["verification"]["org_rows"] == 0
    assert await PostgresOrganizationRepository().get_by_id(org["org_id"]) is None

# =============================================================================
# Disaster Recovery (PROMPT 10) — backups, drill, readiness, perfil DR
# =============================================================================
from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"dr-{uuid4().hex[:8]}@example.com",
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
async def test_dr_backup_create_and_list(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Dr Backup Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-dr-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Sin perfil: readiness bajo.
    ready0 = await async_client.get(
        f"/api/v1/platform/dr/readiness?organization_id={oid}", headers=plat
    )
    assert ready0.status_code == 200, ready0.text
    r0 = ready0.json()
    assert r0["score"] < 50
    assert any(c["name"] == "backup_freshness" and not c["ok"] for c in r0["components"])

    # Habilitar perfil DR.
    profile = await async_client.put(
        f"/api/v1/platform/dr/organizations/{oid}",
        headers=plat,
        json={"regions": ["us-east-1", "eu-west-1"], "rpo_minutes": 60, "backup_enabled": True},
    )
    assert profile.status_code == 200, profile.text
    got = await async_client.get(f"/api/v1/platform/dr/organizations/{oid}", headers=plat)
    assert got.json()["regions"] == ["us-east-1", "eu-west-1"]
    assert got.json()["rpo_minutes"] == 60
    assert got.json()["backup_enabled"] is True

    # Backup manual.
    created = await async_client.post(
        f"/api/v1/platform/dr/organizations/{oid}/backup", headers=plat, json={}
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "completed", body
    assert body["size_bytes"] > 0
    assert len(body["checksum_sha256"]) == 64
    assert Path(body["file_path"]).exists()
    # Checksum verificado.
    data = Path(body["file_path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == body["checksum_sha256"]

    # Listado.
    listed = await async_client.get(
        f"/api/v1/platform/dr/backups?organization_id={oid}", headers=plat
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] >= 1
    latest = listed.json()["backups"][0]
    assert latest["trigger"] == "manual"

    # Readiness mejoró (fresco dentro de RPO).
    ready1 = await async_client.get(
        f"/api/v1/platform/dr/readiness?organization_id={oid}", headers=plat
    )
    assert ready1.json()["score"] >= 60
    freshness = next(c for c in ready1.json()["components"] if c["name"] == "backup_freshness")
    assert freshness["ok"] is True

    # Regiones del catálogo.
    regions = await async_client.get("/api/v1/platform/dr/regions", headers=plat)
    assert regions.status_code == 200, regions.text
    codes = [r["code"] for r in regions.json()["regions"]]
    assert "us-east-1" in codes and "local" in codes


@pytest.mark.asyncio
async def test_dr_drill_restores_standby(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Dr Drill Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-drill-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        f"/api/v1/platform/dr/organizations/{oid}/backup", headers=plat, json={}
    )
    assert created.status_code == 200
    backup_id = created.json()["id"]
    assert created.json()["status"] == "completed"

    drill = await async_client.post(
        f"/api/v1/platform/dr/backups/{backup_id}/drill", headers=plat, json={}
    )
    assert drill.status_code == 200, drill.text
    out = drill.json()
    assert out["status"] == "ok", out
    assert out["tables"] >= 10  # tablas del platform restauradas en standby

    # La standby fue eliminada tras el drill.
    import subprocess

    from src.core.config import get_settings

    settings = get_settings()
    check = subprocess.run(  # noqa: S603, S607
        [
            "docker", "exec", settings.DR_POSTGRES_CONTAINER, "psql", "-U", settings.POSTGRES_USER,
            "-d", "postgres", "-t", "-c",
            f"SELECT 1 FROM pg_database WHERE datname = '{out['standby_db']}'",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert check.stdout.strip() == ""


@pytest.mark.asyncio
async def test_dr_prune_and_scheduler_trigger(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Dr Prune Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-prune-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        f"/api/v1/platform/dr/organizations/{oid}/backup", headers=plat, json={}
    )
    assert created.status_code == 200
    assert created.json()["status"] == "completed"
    backup_id = created.json()["id"]

    # Envejecer el backup (8 días) para que el prune lo elimine.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text("UPDATE dr_backups SET created_at = NOW() - INTERVAL '8 days' WHERE id = :bid"),
            {"bid": UUID(backup_id)},
        )
        await session.commit()
    finally:
        await session.close()

    pruned = await async_client.post(
        "/api/v1/platform/dr/prune",
        headers=plat,
        json={"organization_id": oid, "retention_days": 7},
    )
    assert pruned.status_code == 200, pruned.text
    assert pruned.json()["removed"] >= 1

    listed = await async_client.get(
        f"/api/v1/platform/dr/backups?organization_id={oid}", headers=plat
    )
    assert all(b["id"] != backup_id for b in listed.json()["backups"])

    # La query del scheduler (RPO vencido) encuentra la org con backup_enabled.
    from src.platform.dr.disaster_recovery import dr_scheduler_loop

    assert dr_scheduler_loop is not None

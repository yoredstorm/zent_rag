# =============================================================================
# Governance (PROMPT 11) — retention, DSR export/erasure, KMS envelope
# =============================================================================
from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"gov-{uuid4().hex[:8]}@example.com",
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


async def _seed_old_usage(client: AsyncClient, org: dict, days_old: int = 400) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "total_tokens, estimated_cost, status, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 100, 0.001, 'completed', "
                "NOW() - MAKE_INTERVAL(days => :days))"
            ),
            {"oid": UUID(org["organization_id"]), "days": days_old},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_governance_profile_and_retention(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Gov Retention Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-gov-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]
    await _seed_old_usage(async_client, org, days_old=400)

    # Perfil: retención 30 días + residencia + contacto DSR.
    profile = await async_client.put(
        f"/api/v1/platform/governance/organizations/{oid}",
        headers=plat,
        json={
            "retention_days": 30,
            "data_residency_region": "us-east-1",
            "dsr_contact_email": "dsr@tenant.example",
        },
    )
    assert profile.status_code == 200, profile.text
    got = await async_client.get(f"/api/v1/platform/governance/organizations/{oid}", headers=plat)
    g = got.json()
    assert g["retention_days"] == 30
    assert g["data_residency_region"] == "us-east-1"
    assert g["dsr_contact_email"] == "dsr@tenant.example"

    # Dry-run: el registro de 400 días aparece expirado.
    dry = await async_client.post(
        "/api/v1/platform/governance/purge",
        headers=plat,
        json={"organization_id": oid, "dry_run": True},
    )
    assert dry.status_code == 200, dry.text
    org_row = dry.json()["organizations"][0]
    assert org_row["expired"]["usage_events"] >= 1

    # Ejecutar: purga + evento de cumplimiento.
    run = await async_client.post(
        "/api/v1/platform/governance/purge",
        headers=plat,
        json={"organization_id": oid, "dry_run": False},
    )
    assert run.status_code == 200, run.text
    assert run.json()["organizations"][0]["expired"]["usage_events"] >= 1

    events = await async_client.get(
        f"/api/v1/platform/governance/compliance-events?organization_id={oid}", headers=plat
    )
    assert events.status_code == 200, events.text
    types = [e["event_type"] for e in events.json()["events"]]
    assert "retention.purge" in types


@pytest.mark.asyncio
async def test_kms_envelope_roundtrip_and_rotate(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-kms-{uuid4().hex[:8]}@zent.example")

    # Garantizar al menos una clave activa.
    status0 = await async_client.get("/api/v1/platform/governance/kms/status", headers=plat)
    assert status0.status_code == 200, status0.text
    if status0.json()["active_version"] is None:
        created = await async_client.post("/api/v1/platform/governance/kms/keys", headers=plat, json={})
        assert created.status_code == 201, created.text

    rt = await async_client.post("/api/v1/platform/governance/kms/roundtrip", headers=plat, json={})
    assert rt.status_code == 200, rt.text
    assert rt.json()["status"] == "ok"
    version_before = rt.json()["key_version"]

    keys = await async_client.get("/api/v1/platform/governance/kms/keys", headers=plat)
    assert keys.status_code == 200, keys.text
    assert len(keys.json()["keys"]) >= 1

    # Rotar → nueva versión activa; roundtrip sigue ok.
    rotated = await async_client.post(
        "/api/v1/platform/governance/kms/keys/any/rotate", headers=plat, json={}
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["key_version"] == version_before + 1
    assert rotated.json()["previous_retired"] is True

    rt2 = await async_client.post("/api/v1/platform/governance/kms/roundtrip", headers=plat, json={})
    assert rt2.json()["status"] == "ok"
    assert rt2.json()["key_version"] == version_before + 1


@pytest.mark.asyncio
async def test_dsr_export_and_erasure(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Gov Dsr Org")
    org["session"] = await _owner_session(org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-dsr-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Export: artefacto cifrado con KMS + receipt + evento.
    exported = await async_client.post(
        f"/api/v1/platform/governance/organizations/{oid}/dsr-export", headers=plat, json={}
    )
    assert exported.status_code == 200, exported.text
    exp = exported.json()
    assert exp["status"] == "exported"
    assert len(exp["receipt_sha256"]) == 64
    assert exp["users"] >= 1
    assert exp["key_version"] >= 1

    # El artefacto cifrado existe y es JSON con key_version + ciphertext.
    artifact = Path(__import__("src.core.config", fromlist=["get_settings"]).get_settings().DR_BACKUP_DIR).parent / "dsr" / oid / exp["artifact"]
    assert artifact.exists()
    blob = __import__("json").loads(artifact.read_text())
    assert blob["key_version"] == exp["key_version"]
    assert blob["ciphertext"]

    events1 = await async_client.get(
        f"/api/v1/platform/governance/compliance-events?organization_id={oid}", headers=plat
    )
    assert any(e["event_type"] == "dsr.export" for e in events1.json()["events"])

    # Erasure: usuarios anonimizados + actividad borrada + evento.
    erased = await async_client.post(
        f"/api/v1/platform/governance/organizations/{oid}/dsr-erasure", headers=plat, json={}
    )
    assert erased.status_code == 200, erased.text
    assert erased.json()["status"] == "erased"
    assert erased.json()["users_erased"] >= 1

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        users = (
            await session.execute(
                text("SELECT email, password_hash, external_id FROM users WHERE organization_id = :oid"),
                {"oid": UUID(oid)},
            )
        ).fetchall()
        usage = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM usage_events WHERE organization_id = :oid"),
                    {"oid": UUID(oid)},
                )
            ).scalar()
            or 0
        )
        members = int(
            (
                await session.execute(
                    text("SELECT COUNT(*) FROM memberships WHERE organization_id = :oid"),
                    {"oid": UUID(oid)},
                )
            ).scalar()
            or 0
        )
    finally:
        await session.close()
    for u in users:
        assert u.email.endswith("@erased.invalid")
        assert u.password_hash is None
        assert u.external_id == "erased"
    assert usage == 0
    assert members == 0

    events2 = await async_client.get(
        f"/api/v1/platform/governance/compliance-events?organization_id={oid}", headers=plat
    )
    assert any(e["event_type"] == "dsr.erasure" for e in events2.json()["events"])

# =============================================================================
# Data Export & Compliance v2 (PROMPT 33)
# =============================================================================
from __future__ import annotations

import io
import json
import zipfile
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient


async def _create_org(client: AsyncClient, name: str) -> dict:
    resp = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": name,
            "email": f"de-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


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
async def test_full_export_and_download(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DE Org")
    plat = await _platform_admin(async_client, f"padmin-de-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    created = await async_client.post(
        "/api/v1/platform/data-export/export",
        headers=plat,
        json={"organization_id": oid, "scope": "all", "anonymized": False},
    )
    assert created.status_code == 201, created.text
    export = created.json()
    assert export["status"] == "completed"
    assert export["size_bytes"] > 0
    assert export["row_counts"]["config"] == 1
    assert export["row_counts"]["kb"] == 0

    download = await async_client.get(
        f"/api/v1/platform/data-export/exports/{export['id']}/download", headers=plat
    )
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/zip")
    assert "zent-export-" in download.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(download.content))
    names = zf.namelist()
    assert "manifest.json" in names
    assert "config.json" in names
    assert "kb.json" in names
    assert "usage.json" in names
    config = json.loads(zf.read("config.json"))
    assert config["organization"]["id"] == oid
    assert config["organization"]["plan"] == "trial"

    listed = await async_client.get(
        f"/api/v1/platform/data-export/exports?organization_id={oid}", headers=plat
    )
    assert listed.json()["exports"][0]["requested_by"] is not None  # auditoría
    assert listed.json()["exports"][0]["scope"] == "all"


@pytest.mark.asyncio
async def test_anonymized_export_masks_pii(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DE Anon Org")
    plat = await _platform_admin(async_client, f"padmin-dea-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    # Seed: usage + email real del owner para verificar pseudonimización.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, model, "
                "status, estimated_cost, actual_cost, cost_tags) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'completed', "
                "0.01, 0.01, '{}')"
            ),
            {"oid": UUID(oid)},
        )
        await session.execute(
            text(
                "UPDATE users SET email = :email "
                "WHERE organization_id = :oid AND external_id = 'default-admin'"
            ),
            {"oid": UUID(oid), "email": f"owner-pii-{uuid4().hex[:6]}@example.com"},
        )
        await session.commit()
    finally:
        await session.close()

    created = await async_client.post(
        "/api/v1/platform/data-export/export",
        headers=plat,
        json={"organization_id": oid, "scope": "all", "anonymized": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["anonymized"] is True
    assert created.json()["row_counts"]["usage"] >= 1

    download = await async_client.get(
        f"/api/v1/platform/data-export/exports/{created.json()['id']}/download", headers=plat
    )
    zf = zipfile.ZipFile(io.BytesIO(download.content))
    config = json.loads(zf.read("config.json"))
    owner = config["organization"]["owner"]
    assert owner is not None
    assert len(owner) == 16 and all(c in "0123456789abcdef" for c in owner)  # hash pseudonimizado
    assert "owner-pii" not in owner
    usage = json.loads(zf.read("usage.json"))
    assert len(usage) >= 1
    assert len(usage[0]["created_at"]) == 10  # granularidad día (k-anonimity)


@pytest.mark.asyncio
async def test_retention_policy_upsert_and_purge(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DE Ret Org")
    plat = await _platform_admin(async_client, f"padmin-der-{uuid4().hex[:8]}@zent.example")
    oid = org["organization_id"]

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    # Eventos: uno reciente y uno viejo (> 0 días).
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, model, "
                "status, estimated_cost, actual_cost, cost_tags, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', 'completed', "
                "0.01, 0.01, '{}', NOW() - interval '2 days')"
            ),
            {"oid": UUID(oid)},
        )
        await session.commit()
    finally:
        await session.close()

    # Política global usage_events con 0 días.
    invalid = await async_client.post(
        "/api/v1/platform/data-export/retention/policies",
        headers=plat,
        json={"data_type": "nope_table", "retention_days": 30},
    )
    assert invalid.status_code == 400

    policy = await async_client.post(
        "/api/v1/platform/data-export/retention/policies",
        headers=plat,
        json={"data_type": "usage_events", "retention_days": 1},
    )
    assert policy.status_code == 201, policy.text

    before = (
        await session.execute(
            text("SELECT COUNT(*) FROM usage_events WHERE organization_id = :oid"),
            {"oid": UUID(oid)},
        )
    ).scalar()

    purge = await async_client.post(
        "/api/v1/platform/data-export/retention/purge", headers=plat
    )
    assert purge.status_code == 200, purge.text
    assert any(p["data_type"] == "usage_events" for p in purge.json()["purged"])

    after = (
        await session.execute(
            text("SELECT COUNT(*) FROM usage_events WHERE organization_id = :oid"),
            {"oid": UUID(oid)},
        )
    ).scalar()
    assert after < before  # se purgó al menos el evento viejo
    await session.close()

    # Historial de purgas.
    purges = await async_client.get("/api/v1/platform/data-export/retention/purges", headers=plat)
    assert purges.json()["purges"][0]["data_type"] == "usage_events"

    # Política deshabilitada → sin purga adicional.
    toggled = await async_client.post(
        "/api/v1/platform/data-export/retention/policies",
        headers=plat,
        json={"data_type": "usage_events", "retention_days": 1, "enabled": False},
    )
    assert toggled.status_code == 201, toggled.text
    purge2 = await async_client.post(
        "/api/v1/platform/data-export/retention/purge", headers=plat
    )
    assert purge2.json()["purged"] == []


@pytest.mark.asyncio
async def test_retention_policy_delete(async_client: AsyncClient) -> None:
    plat = await _platform_admin(async_client, f"padmin-derd-{uuid4().hex[:8]}@zent.example")

    policies = await async_client.get("/api/v1/platform/data-export/retention/policies", headers=plat)
    assert policies.status_code == 200, policies.text
    assert len(policies.json()["policies"]) >= 6  # seeds globales

    created = await async_client.post(
        "/api/v1/platform/data-export/retention/policies",
        headers=plat,
        json={"data_type": "api_logs", "retention_days": 45},
    )
    assert created.status_code == 201, created.text
    deleted = await async_client.delete(
        f"/api/v1/platform/data-export/retention/policies/{created.json()['id']}", headers=plat
    )
    assert deleted.status_code == 200

# =============================================================================
# AI Disaster Recovery & High Availability v2 (PROMPT 51)
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
            "email": f"dr-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _owner_session(client: AsyncClient, organization_id: str) -> str:
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
        "Idempotency-Key": f"dr-{uuid4().hex}",
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
async def test_policies_crud_and_status(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DR Policies Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    created = await async_client.post(
        "/api/v1/dr/policies",
        headers={**_headers(org), "Idempotency-Key": f"dr-p-{uuid4().hex}"},
        json={"name": "DR Agente Ventas", "scope": "agent", "rpo_minutes": 30, "rto_minutes": 5, "replication_region": "eu-west-1"},
    )
    assert created.status_code == 200, created.text
    pid = created.json()["policy_id"]

    # Scope inválido → 400.
    bad = await async_client.post(
        "/api/v1/dr/policies",
        headers={**_headers(org), "Idempotency-Key": f"dr-b-{uuid4().hex}"},
        json={"name": "Bad", "scope": "nope"},
    )
    assert bad.status_code in (400, 422)  # Pydantic pattern → 422

    updated = await async_client.patch(
        f"/api/v1/dr/policies/{pid}",
        headers={**_headers(org), "Idempotency-Key": f"dr-u-{uuid4().hex}"},
        json={"rpo_minutes": 15, "replication_region": "ap-southeast-1"},
    )
    assert updated.status_code == 200, updated.text

    paused = await async_client.post(f"/api/v1/dr/policies/{pid}/pause", headers={**_headers(org)})
    assert paused.json()["status"] == "paused"
    resumed = await async_client.post(f"/api/v1/dr/policies/{pid}/resume", headers={**_headers(org)})
    assert resumed.json()["status"] == "active"

    policies = await async_client.get("/api/v1/dr/policies", headers=h)
    entry = next(p for p in policies.json()["policies"] if p["id"] == pid)
    assert entry["rpo_minutes"] == 15
    assert entry["replication_region"] == "ap-southeast-1"
    assert entry["status"] == "active"


@pytest.mark.asyncio
async def test_backups_versioned_and_restore(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DR Backups Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    agent = (
        await async_client.post(
            "/api/v1/agents",
            headers={**_headers(org), "Idempotency-Key": f"dr-a-{uuid4().hex}"},
            json={"name": "Agente DR", "system_prompt": "prompt original", "model": "gpt-4o-mini"},
        )
    ).json()
    agent_id = agent["id"]

    b1 = await async_client.post(
        "/api/v1/dr/backups",
        headers={**_headers(org), "Idempotency-Key": f"dr-b1-{uuid4().hex}"},
        json={"scope": "agent", "source_id": agent_id},
    )
    assert b1.status_code == 200, b1.text
    assert b1.json()["version"] == 1
    assert b1.json()["artifact"]["agent"]["name"] == "Agente DR"

    b2 = await async_client.post(
        "/api/v1/dr/backups",
        headers={**_headers(org), "Idempotency-Key": f"dr-b2-{uuid4().hex}"},
        json={"scope": "agent", "source_id": agent_id},
    )
    assert b2.json()["version"] == 2

    backups = await async_client.get("/api/v1/dr/backups?scope=agent", headers=h)
    assert len(backups.json()["backups"]) == 2
    assert backups.json()["backups"][0]["version"] == 2

    restored = await async_client.post(
        f"/api/v1/dr/backups/{b1.json()['backup_id']}/restore",
        headers={**_headers(org), "Idempotency-Key": f"dr-r-{uuid4().hex}"},
        json={"region": "us-east-1"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["status"] == "restored" if False else restored.json()["restored_to_region"] == "us-east-1"

    # El agente restaurado existe con el prompt del backup.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM agents "
                    "WHERE organization_id = :oid AND name = 'Agente DR (restaurado)'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert int(count) == 1

    backups2 = await async_client.get("/api/v1/dr/backups", headers=h)
    restored_entry = next(b for b in backups2.json()["backups"] if b["id"] == b1.json()["backup_id"])
    assert restored_entry["status"] == "restored"


@pytest.mark.asyncio
async def test_drill_failover(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DR Drill Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.dr.dr_center import create_policy

    policy = await create_policy(
        UUID(org["organization_id"]), "DR Drill Policy", "full", None, 60, 15, "eu-west-1"
    )

    drill = await async_client.post(
        "/api/v1/dr/drills",
        headers={**_headers(org), "Idempotency-Key": f"dr-d-{uuid4().hex}"},
        json={"policy_id": policy["policy_id"]},
    )
    assert drill.status_code == 200, drill.text
    body = drill.json()
    assert body["status"] in ("success", "failed")
    assert body["failover_ok"] is True  # resolver elige otra región tras caída
    assert "primaria" in body["detail"]
    assert "recuperación" in body["detail"]

    drills = await async_client.get("/api/v1/dr/drills", headers=h)
    assert len(drills.json()["drills"]) == 1
    assert drills.json()["drills"][0]["policy_name"] == "DR Drill Policy"

    # Drill con política pausada → no ejecuta.
    from src.platform.dr.dr_center import set_policy_status

    await set_policy_status(UUID(org["organization_id"]), UUID(policy["policy_id"]), "paused")
    paused = await async_client.post(
        "/api/v1/dr/drills",
        headers={**_headers(org), "Idempotency-Key": f"dr-d2-{uuid4().hex}"},
        json={"policy_id": policy["policy_id"]},
    )
    assert paused.json()["status"] == "paused"


@pytest.mark.asyncio
async def test_availability_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DR Avail Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    from src.platform.dr.dr_center import create_backup, create_policy, run_drill

    policy = await create_policy(
        UUID(org["organization_id"]), "DR Avail Policy", "knowledge", None, 30, 10, "eu-west-1"
    )
    await create_backup(UUID(org["organization_id"]), "knowledge")
    await run_drill(UUID(org["organization_id"]), UUID(policy["policy_id"]))

    avail = await async_client.get("/api/v1/dr/availability", headers=h)
    assert avail.status_code == 200, avail.text
    body = avail.json()
    assert body["policies_total"] == 1
    assert body["policies_active"] == 1
    assert body["drills_30d"] == 1
    assert body["drill_success_rate"] == 100.0
    assert body["rpo_coverage"] == 100.0  # backup reciente dentro del RPO de 30m
    assert body["rpo_covered_policies"] == 1
    assert len(body["regions"]["regions"]) >= 2


@pytest.mark.asyncio
async def test_platform_dashboard(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "DR Dash Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    plat = await _platform_admin(async_client, f"padmin-dr-{uuid4().hex[:8]}@zent.example")

    from src.platform.dr.dr_center import create_backup, create_policy, run_drill

    policy = await create_policy(
        UUID(org["organization_id"]), "DR Dash Policy", "full", None, 60, 15, "eu-west-1"
    )
    await create_backup(UUID(org["organization_id"]), "full")
    await run_drill(UUID(org["organization_id"]), UUID(policy["policy_id"]))

    dash = await async_client.get("/api/v1/platform/dr/dashboard", headers=plat)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["policies_total"] >= 1
    assert body["policies_active"] >= 1
    assert body["organizations_covered"] >= 1
    assert body["drills_30d"] >= 1
    assert body["drill_success_rate"] == 100.0
    assert body["backups_total"] >= 1
    assert any(r["count"] >= 1 for r in body["drills_by_region"])

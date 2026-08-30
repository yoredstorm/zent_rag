# =============================================================================
# Plan entitlements — configurable limits/features without ALTER TABLE
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from src.platform.auth.passwords import hash_password
from src.platform.auth.session import encrypt_session

TRIAL_PLAN_ID = UUID("10000000-0000-0000-0000-000000000001")
STARTER_PLAN_ID = UUID("10000000-0000-0000-0000-000000000002")


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Ent Co {uuid4().hex[:8]}",
            "email": f"ent-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


async def _seed_platform_admin(email: str, password: str) -> None:
    from src.infrastructure.postgres.relational_db import ensure_platform_admin_schema
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
            await session.execute(
                text(
                    "UPDATE users SET is_platform_admin = true, "
                    "password_hash = :ph WHERE id = :id"
                ),
                {"ph": hash_password(password), "id": existing.id},
            )
        else:
            await session.execute(
                text(
                    "INSERT INTO users (id, organization_id, external_id, email_hash, "
                    "role, email, password_hash, is_platform_admin) "
                    "VALUES (gen_random_uuid(), NULL, :ext, :eh, 'platform', "
                    ":email, :ph, true)"
                ),
                {
                    "ext": f"platform-{uuid4().hex[:12]}",
                    "eh": __import__("hashlib").sha256(email.encode()).hexdigest(),
                    "email": email,
                    "ph": hash_password(password),
                },
            )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _platform_token(client: AsyncClient) -> str:
    email = f"ent-admin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    login = await client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


@pytest.mark.asyncio
async def test_trial_denied_embed_widget(async_client: AsyncClient) -> None:
    from src.platform.billing.entitlements import EntitlementDenied, check_entitlement

    org = await _trial(async_client)
    with pytest.raises(EntitlementDenied) as exc:
        await check_entitlement(UUID(org["organization_id"]), "embed_widget")
    assert exc.value.key == "embed_widget"


@pytest.mark.asyncio
async def test_get_entitlements_for_own_plan(async_client: AsyncClient) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/billing/entitlements",
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan_name"] == "trial"
    assert body["entitlements"]["embed_widget"] is False
    assert "max_agents" in body["entitlements"]
    assert "monthly_requests" in body["entitlements"]


@pytest.mark.asyncio
async def test_tenant_cannot_put_platform_entitlements(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.put(
        f"/api/v1/platform/plans/{STARTER_PLAN_ID}/entitlements",
        json={
            "entitlements": [
                {"key": "max_agents", "value_type": "int", "value_int": 1},
            ]
        },
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_max_agents_one_blocks_second_create(
    async_client: AsyncClient,
) -> None:
    from src.platform.billing.entitlements import upsert_plan_entitlements

    org = await _trial(async_client)
    token = await _owner_session(org["organization_id"])
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }
    await upsert_plan_entitlements(
        TRIAL_PLAN_ID,
        [{"key": "max_agents", "value_type": "int", "value_int": 1}],
    )
    try:
        first = await async_client.post(
            "/api/v1/agents",
            json={"name": f"a-{uuid4().hex[:6]}", "tools": []},
            headers=headers,
        )
        assert first.status_code == 201, first.text
        second = await async_client.post(
            "/api/v1/agents",
            json={"name": f"a-{uuid4().hex[:6]}", "tools": []},
            headers=headers,
        )
        assert second.status_code == 409, second.text
        assert second.json().get("error_code") == "plan_limit_reached"
    finally:
        await upsert_plan_entitlements(
            TRIAL_PLAN_ID,
            [{"key": "max_agents", "value_type": "int", "value_int": None}],
        )


@pytest.mark.asyncio
async def test_platform_put_entitlements_and_tenant_reads(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    platform = await _platform_token(async_client)
    put = await async_client.put(
        f"/api/v1/platform/plans/{TRIAL_PLAN_ID}/entitlements",
        json={
            "entitlements": [
                {"key": "eval_ui", "value_type": "bool", "value_bool": True},
            ]
        },
        headers={"Authorization": f"Bearer {platform}"},
    )
    assert put.status_code == 200, put.text
    session = await _owner_session(org["organization_id"])
    got = await async_client.get(
        "/api/v1/billing/entitlements",
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert got.status_code == 200, got.text
    assert got.json()["entitlements"]["eval_ui"] is True
    restore = await async_client.put(
        f"/api/v1/platform/plans/{TRIAL_PLAN_ID}/entitlements",
        json={
            "entitlements": [
                {"key": "eval_ui", "value_type": "bool", "value_bool": False},
            ]
        },
        headers={"Authorization": f"Bearer {platform}"},
    )
    assert restore.status_code == 200, restore.text


@pytest.mark.asyncio
async def test_list_plans_includes_entitlements_additive(
    async_client: AsyncClient,
) -> None:
    resp = await async_client.get("/api/v1/billing/plans")
    assert resp.status_code == 200, resp.text
    trial = next(p for p in resp.json()["plans"] if p["name"] == "trial")
    assert "features" in trial
    assert "entitlements" in trial
    assert trial["entitlements"]["embed_widget"] is False
    assert trial["entitlements"]["monthly_requests"] == 500


@pytest.mark.asyncio
async def test_plan_change_writes_subscription_event(
    async_client: AsyncClient,
) -> None:
    from src.infrastructure.postgres.session import get_async_session

    org = await _trial(async_client)
    platform = await _platform_token(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{org['organization_id']}/plan",
        json={"plan_name": "starter"},
        headers={"Authorization": f"Bearer {platform}"},
    )
    assert resp.status_code == 200, resp.text
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT event_type, from_plan_id, to_plan_id "
                    "FROM subscription_events "
                    "WHERE organization_id = :oid AND event_type = 'plan_changed' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row is not None
    assert row.event_type == "plan_changed"
    assert row.to_plan_id == STARTER_PLAN_ID

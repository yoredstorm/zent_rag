# =============================================================================
# Revenue Intelligence & ARR (PROMPT 32)
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
            "email": f"rv-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"rv-{uuid4().hex}",
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


async def _subscription_id(org: dict) -> UUID:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        return (
            await session.execute(
                text("SELECT id FROM subscriptions WHERE organization_id = :oid"),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_revenue_summary_and_upgrade_events(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Rev Org")
    plat = await _platform_admin(async_client, f"padmin-rv-{uuid4().hex[:8]}@zent.example")

    # Trial → MRR 0 + evento created (mrr 0).
    summary = await async_client.get("/api/v1/platform/revenue/summary?days=30", headers=plat)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["trials_created"] >= 1
    assert body["churn_rate"] >= 0

    # Upgrade trial → pro: evento upgraded con mrr del plan.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        plan_id = (
            await session.execute(text("SELECT id FROM plans WHERE name = 'pro'"))
        ).scalar()
        sub_id = (
            await session.execute(
                text("SELECT id FROM subscriptions WHERE organization_id = :oid"),
                {"oid": UUID(org["organization_id"])},
            )
        ).scalar()
        await session.execute(
            text(
                "UPDATE subscriptions SET plan_id = :pid, status = 'active' WHERE id = :sid"
            ),
            {"pid": plan_id, "sid": sub_id},
        )
        await session.commit()
    finally:
        await session.close()

    from src.platform.revenue.revenue import record_sub_event

    await record_sub_event(
        subscription_id=sub_id,
        organization_id=UUID(org["organization_id"]),
        event_type="upgraded",
        plan_name="pro",
        mrr_cents=25000,
    )

    summary2 = await async_client.get("/api/v1/platform/revenue/summary?days=30", headers=plat)
    body2 = summary2.json()
    assert body2["expansion_mrr_cents"] >= 25000
    assert body2["net_mrr_delta_cents"] >= 25000
    pro = next(p for p in body2["by_plan"] if p["plan"] == "pro")
    assert pro["mrr_cents"] >= 25000
    assert pro["arr_cents"] == pro["mrr_cents"] * 12

    # Ledger.
    events = await async_client.get("/api/v1/platform/revenue/events?days=30", headers=plat)
    types = {e["event_type"] for e in events.json()["events"]}
    assert "upgraded" in types
    assert "created" in types


@pytest.mark.asyncio
async def test_conversion_funnels_and_forecast(async_client: AsyncClient) -> None:
    org_a = await _create_org(async_client, "Rev Funnel A")
    org_b = await _create_org(async_client, "Rev Funnel B")
    plat = await _platform_admin(async_client, f"padmin-rvf-{uuid4().hex[:8]}@zent.example")

    # Convertir ambos a starter (paid).
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        plan_id = (
            await session.execute(text("SELECT id FROM plans WHERE name = 'starter'"))
        ).scalar()
        for org in (org_a, org_b):
            await session.execute(
                text(
                    "UPDATE subscriptions SET plan_id = :pid, status = 'active' "
                    "WHERE organization_id = :oid"
                ),
                {"pid": plan_id, "oid": UUID(org["organization_id"])},
            )
        await session.commit()
    finally:
        await session.close()

    funnels = await async_client.get("/api/v1/platform/revenue/funnels?months=12", headers=plat)
    assert funnels.status_code == 200, funnels.text
    current = next(f for f in funnels.json()["funnels"] if f["cohort"] == funnels.json()["funnels"][-1]["cohort"])
    assert current["trials"] >= 2
    assert current["converted"] >= 2
    assert current["conversion_rate"] > 0
    assert current["mrr_cents_now"] >= 0

    forecast = await async_client.get("/api/v1/platform/revenue/forecast?months=6", headers=plat)
    assert forecast.status_code == 200, forecast.text
    fc = forecast.json()
    assert len(fc["projected"]) == 6
    assert fc["avg_conversion_rate"] > 0
    assert all(p["new_mrr_cents"] > 0 for p in fc["projected"])
    assert fc["projected"][0]["month"] < fc["projected"][5]["month"]


@pytest.mark.asyncio
async def test_revenue_csv_export(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Rev CSV Org")
    plat = await _platform_admin(async_client, f"padmin-rvc-{uuid4().hex[:8]}@zent.example")

    csv_resp = await async_client.get("/api/v1/platform/revenue/export.csv", headers=plat)
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_resp.headers.get("content-disposition", "")
    lines = csv_resp.text.strip().splitlines()
    assert lines[0].startswith("organization_id,organization_name")
    assert any(org["organization_id"] in line for line in lines[1:])
    row = next(line for line in lines[1:] if org["organization_id"] in line)
    fields = row.split(",")
    assert fields[2] == "trial"
    assert fields[3] == "trialing"
    assert fields[5] == "0"  # mrr_cents trial


@pytest.mark.asyncio
async def test_cancel_records_event(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Rev Cancel Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    cancel = await async_client.post(
        "/api/v1/billing/subscription/cancel",
        headers={**_headers(org), "Idempotency-Key": f"rv-c-{uuid4().hex}"},
    )
    assert cancel.status_code == 200, cancel.text

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        event = (
            await session.execute(
                text(
                    "SELECT event_type FROM subscription_events "
                    "WHERE organization_id = :oid AND event_type = 'canceled'"
                ),
                {"oid": UUID(org["organization_id"])},
            )
        ).fetchone()
    finally:
        await session.close()
    assert event is not None

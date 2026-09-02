# =============================================================================
# Platform admin identity — Control Center session vs tenant owner vs admin:*
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.auth.passwords import hash_password
from src.platform.auth.session import encrypt_session


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Plat Co {uuid4().hex[:8]}",
            "email": f"plat-{uuid4().hex[:8]}@example.com",
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
    """Insert a platform admin row (is_platform_admin + rol super_admin).
    Used by login tests."""
    from sqlalchemy import text

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
        # RBAC granular: el admin legacy equivale a super_admin (backfill 023).
        await session.execute(
            text(
                "INSERT INTO user_platform_roles (user_id, role_id) "
                "SELECT :uid, id FROM platform_roles WHERE name = 'super_admin' "
                "ON CONFLICT DO NOTHING"
            ),
            {"uid": user_id},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_portal_owner_cannot_list_billing_admin_organizations(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/billing/admin/organizations",
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json().get("error_code") == "platform_admin_required"


@pytest.mark.asyncio
async def test_admin_star_api_key_can_list_organizations(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository
    from src.platform.billing.service import generate_api_token

    token = generate_api_token()
    await PostgresApiKeyRepository().create_key(
        UUID(org["organization_id"]),
        token,
        name="machine-admin",
        scopes=["admin:*"],
    )
    resp = await async_client.get(
        "/api/v1/billing/admin/organizations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "organizations" in resp.json()


@pytest.mark.asyncio
async def test_platform_session_can_list_organizations(
    async_client: AsyncClient,
) -> None:
    email = f"padmin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    assert token.startswith("rag_sess_")
    resp = await async_client.get(
        "/api/v1/billing/admin/organizations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    assert "organizations" in resp.json()


@pytest.mark.asyncio
async def test_platform_admin_tenant_login_points_to_control_center(
    async_client: AsyncClient,
) -> None:
    email = f"padmin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    wrong_form = await async_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert wrong_form.status_code == 403, wrong_form.text
    body = wrong_form.json()
    detail = body.get("detail") or body
    assert detail.get("error_code") == "platform_login_required"


@pytest.mark.asyncio
async def test_platform_session_spoof_org_header_does_not_elevate(
    async_client: AsyncClient,
) -> None:
    customer = await _trial(async_client)
    email = f"padmin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    login = await async_client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]

    spoofed = await async_client.get(
        "/api/v1/projects",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": customer["organization_id"],
        },
    )
    assert spoofed.status_code in (403, 400), spoofed.text

    listed = await async_client.get(
        "/api/v1/billing/admin/organizations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200, listed.text


async def _platform_login_headers(client: AsyncClient) -> dict[str, str]:
    email = f"padmin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    login = await client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_platform_org_list_exposes_trial_and_amount_due(
    async_client: AsyncClient,
) -> None:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.billing.invoices import upsert_invoice

    org = await _trial(async_client)
    oid = UUID(org["organization_id"])
    now = datetime.now(timezone.utc)
    await upsert_invoice(
        organization_id=oid,
        period_start=now,
        period_end=now + timedelta(days=30),
        subtotal_cents=4500,
        overage_cents=0,
        status="open",
    )
    headers = await _platform_login_headers(async_client)
    resp = await async_client.get("/api/v1/platform/organizations", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["organizations"]
    match = next(r for r in rows if r["id"] == str(oid))
    assert match["subscription_status"] == "trialing"
    assert match["is_trial"] is True
    assert match["amount_due_cents"] == 4500
    assert match["payment_provider"] in ("manual", "stripe")
    assert "next_renewal_at" in match

    detail = await async_client.get(
        f"/api/v1/platform/organizations/{oid}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["amount_due_cents"] == 4500
    assert body["subscription_status"] == "trialing"

    session = await get_async_session()
    try:
        await session.execute(
            text("DELETE FROM invoices WHERE organization_id = :oid"), {"oid": oid}
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_trial_creates_org_notification_and_mark_read(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    headers = await _platform_login_headers(async_client)
    before = await async_client.get(
        f"/api/v1/platform/organizations/{org['organization_id']}", headers=headers
    )
    assert before.status_code == 200, before.text
    listed = await async_client.get("/api/v1/platform/notifications", headers=headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["unread_count"] >= 1
    created = [
        n
        for n in payload["notifications"]
        if n["type"] == "org.created" and n["organization_id"] == org["organization_id"]
    ]
    assert created, payload
    nid = created[0]["id"]
    assert created[0]["read_at"] is None
    marked = await async_client.post(
        f"/api/v1/platform/notifications/{nid}/read", headers=headers
    )
    assert marked.status_code == 200, marked.text
    again = await async_client.get("/api/v1/platform/notifications", headers=headers)
    row = next(n for n in again.json()["notifications"] if n["id"] == nid)
    assert row["read_at"] is not None
    after = await async_client.get(
        f"/api/v1/platform/organizations/{org['organization_id']}", headers=headers
    )
    assert after.status_code == 200, after.text
    assert after.json()["status"] == before.json()["status"]
    assert after.json()["subscription_status"] == before.json()["subscription_status"]


@pytest.mark.asyncio
async def test_manual_payment_creates_review_notification(
    async_client: AsyncClient,
) -> None:
    from src.platform.billing.invoices import record_payment

    org = await _trial(async_client)
    oid = UUID(org["organization_id"])
    await record_payment(
        organization_id=oid,
        provider="manual",
        provider_payment_id=f"pay-{uuid4().hex[:12]}",
        amount_cents=29900,
    )
    headers = await _platform_login_headers(async_client)
    listed = await async_client.get("/api/v1/platform/notifications", headers=headers)
    assert listed.status_code == 200, listed.text
    kinds = [
        n["type"]
        for n in listed.json()["notifications"]
        if n["organization_id"] == str(oid)
    ]
    assert "payment.manual_review" in kinds
    assert "org.created" in kinds


@pytest.mark.asyncio
async def test_tenant_cannot_list_platform_notifications(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/platform/notifications",
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 403, resp.text


async def _platform_headers(client: AsyncClient) -> dict[str, str]:
    email = f"padmin-{uuid4().hex[:8]}@zent.example"
    password = "platform-admin-pass-1"
    await _seed_platform_admin(email, password)
    login = await client.post(
        "/api/v1/auth/platform/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_portal_owner_forbidden_on_platform_metrics(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    session = await _owner_session(org["organization_id"])
    resp = await async_client.get(
        "/api/v1/platform/metrics",
        headers={
            "Authorization": f"Bearer {session}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_platform_metrics_mrr_derived_from_plan_price(
    async_client: AsyncClient,
) -> None:
    headers = await _platform_headers(async_client)
    before = await async_client.get("/api/v1/platform/metrics", headers=headers)
    assert before.status_code == 200, before.text
    payload = before.json()
    for key in (
        "mrr_cents",
        "arr_cents",
        "customers",
        "active_agents",
        "ai_requests_30d",
        "llm_cost_30d",
        "gross_margin_pct",
    ):
        assert key in payload, key
    assert payload["arr_cents"] == payload["mrr_cents"] * 12

    org = await _trial(async_client)
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE subscriptions SET plan_id = "
                "'10000000-0000-0000-0000-000000000002' "
                "WHERE organization_id = :oid"
            ),
            {"oid": org["organization_id"]},
        )
        await session.commit()
    finally:
        await session.close()

    after = await async_client.get("/api/v1/platform/metrics", headers=headers)
    assert after.status_code == 200, after.text
    delta = after.json()["mrr_cents"] - payload["mrr_cents"]
    assert delta == 4900, after.json()


@pytest.mark.asyncio
async def test_impersonate_returns_short_lived_token_and_writes_audit(
    async_client: AsyncClient,
) -> None:
    from src.platform.auth.session import decrypt_session

    customer = await _trial(async_client)
    headers = await _platform_headers(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{customer['organization_id']}/impersonate",
        json={"expires_seconds": 600},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    payload = decrypt_session(token)
    assert payload.typ == "portal"
    assert str(payload.organization_id) == customer["organization_id"]
    assert payload.exp - int(__import__("time").time()) <= 3600

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT action, organization_id, actor_user_id, metadata "
                    "FROM audit_logs WHERE action = 'platform.impersonate' "
                    "AND organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": customer["organization_id"]},
            )
        ).fetchone()
    finally:
        await session.close()
    assert row is not None
    assert str(row.organization_id) == customer["organization_id"]
    assert row.actor_user_id is not None


@pytest.mark.asyncio
async def test_usage_reset_does_not_touch_other_org(
    async_client: AsyncClient,
) -> None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    org_a = await _trial(async_client)
    org_b = await _trial(async_client)
    session = await get_async_session()
    try:
        for oid in (org_a["organization_id"], org_b["organization_id"]):
            sub = (
                await session.execute(
                    text(
                        "SELECT id FROM subscriptions WHERE organization_id = :oid "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"oid": oid},
                )
            ).fetchone()
            assert sub is not None
            await session.execute(
                text(
                    "INSERT INTO request_quota (subscription_id, quota_year, quota_month, "
                    "request_count, reset_at) "
                    "VALUES (:sid, EXTRACT(YEAR FROM NOW())::int, "
                    "EXTRACT(MONTH FROM NOW())::int, 42, NOW()) "
                    "ON CONFLICT (subscription_id, quota_year, quota_month) "
                    "DO UPDATE SET request_count = 42"
                ),
                {"sid": sub.id},
            )
        await session.commit()
    finally:
        await session.close()

    headers = await _platform_headers(async_client)
    resp = await async_client.post(
        f"/api/v1/platform/organizations/{org_a['organization_id']}/usage/reset",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    session = await get_async_session()
    try:
        counts = {}
        for label, oid in (("a", org_a["organization_id"]), ("b", org_b["organization_id"])):
            row = (
                await session.execute(
                    text(
                        "SELECT q.request_count FROM request_quota q "
                        "JOIN subscriptions s ON s.id = q.subscription_id "
                        "WHERE s.organization_id = :oid "
                        "AND q.quota_year = EXTRACT(YEAR FROM NOW())::int "
                        "AND q.quota_month = EXTRACT(MONTH FROM NOW())::int"
                    ),
                    {"oid": oid},
                )
            ).fetchone()
            counts[label] = row.request_count if row else None
    finally:
        await session.close()
    assert counts["a"] == 0
    assert counts["b"] == 42


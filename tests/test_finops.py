# =============================================================================
# FinOps — platform revenue vs LLM/embedding/storage/infra (no demo numbers)
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from src.platform.auth.passwords import hash_password
from src.platform.auth.session import encrypt_session
from src.platform.billing.invoices import mark_invoice_paid, upsert_invoice
from src.platform.usage.usage_engine import UsageEvent, ensure_usage_table, record_event


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"FinOps Co {uuid4().hex[:8]}",
            "email": f"finops-{uuid4().hex[:8]}@example.com",
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


async def _seed_paid_invoice(organization_id: str, total_cents: int) -> None:
    now = datetime.now(timezone.utc)
    pid = f"finops-{uuid4().hex}"
    await upsert_invoice(
        organization_id=UUID(organization_id),
        period_start=now - timedelta(days=20),
        period_end=now - timedelta(days=1),
        subtotal_cents=total_cents,
        overage_cents=0,
        provider_invoice_id=pid,
        status="draft",
    )
    await mark_invoice_paid(pid)


async def _seed_usage(
    organization_id: str,
    *,
    llm_cost: float,
    embedding_cost: float,
) -> None:
    await ensure_usage_table()
    oid = UUID(organization_id)
    await record_event(
        UsageEvent(
            request_id=uuid4(),
            organization_id=oid,
            event_type="rag_query",
            model="gpt-4o-mini",
            provider="openai",
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            estimated_cost=llm_cost,
        )
    )
    await record_event(
        UsageEvent(
            request_id=uuid4(),
            organization_id=oid,
            event_type="rag_query",
            model="openai/baai/bge-m3",
            provider="openai",
            embedding_tokens=8000,
            estimated_cost=embedding_cost,
        )
    )


@pytest.mark.asyncio
async def test_org_finops_margin_is_reproducible_from_invoice_and_usage(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    await _seed_paid_invoice(org["organization_id"], 29900)
    await _seed_usage(org["organization_id"], llm_cost=1.00, embedding_cost=0.25)

    headers = await _platform_headers(async_client)
    resp = await async_client.get(
        f"/api/v1/platform/finops/organizations/{org['organization_id']}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revenue_cents"] == 29900
    assert data["costs"]["llm"] == pytest.approx(1.00)
    assert data["costs"]["embedding"] == pytest.approx(0.25)
    assert "storage" in data["costs"]
    assert "infra" in data["costs"]
    total_cost = (
        data["costs"]["llm"]
        + data["costs"]["embedding"]
        + data["costs"]["storage"]
        + data["costs"]["infra"]
    )
    expected_profit = 299.00 - total_cost
    assert data["gross_profit"] == pytest.approx(expected_profit)
    assert data["gross_margin_pct"] == pytest.approx(
        round(expected_profit / 299.00 * 100.0, 2)
    )
    assert "period" in data
    assert "start" in data["period"] and "end" in data["period"]


@pytest.mark.asyncio
async def test_platform_finops_summary_exposes_contract_and_economics(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    await _seed_paid_invoice(org["organization_id"], 29900)
    await _seed_usage(org["organization_id"], llm_cost=1.00, embedding_cost=0.25)

    headers = await _platform_headers(async_client)
    resp = await async_client.get("/api/v1/platform/finops/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revenue_cents"] >= 29900
    assert set(data["costs"]) == {"llm", "embedding", "storage", "infra"}
    assert "gross_profit" in data
    assert "gross_margin_pct" in data
    assert set(data["customers"]) == {"new", "churned", "arpu_cents"}
    economics = data["economics"]
    for key in (
        "cost_per_request",
        "cost_per_customer",
        "revenue_per_request",
        "margin_per_customer",
        "requests",
    ):
        assert key in economics
    assert "mrr_cents" in data


@pytest.mark.asyncio
async def test_org_a_usage_and_invoices_do_not_leak_into_org_b_finops(
    async_client: AsyncClient,
) -> None:
    org_a = await _trial(async_client)
    org_b = await _trial(async_client)
    await _seed_paid_invoice(org_a["organization_id"], 29900)
    await _seed_usage(org_a["organization_id"], llm_cost=2.00, embedding_cost=0.50)
    await _seed_paid_invoice(org_b["organization_id"], 9900)
    await _seed_usage(org_b["organization_id"], llm_cost=0.10, embedding_cost=0.05)

    headers = await _platform_headers(async_client)
    a = (
        await async_client.get(
            f"/api/v1/platform/finops/organizations/{org_a['organization_id']}",
            headers=headers,
        )
    ).json()
    b = (
        await async_client.get(
            f"/api/v1/platform/finops/organizations/{org_b['organization_id']}",
            headers=headers,
        )
    ).json()
    assert a["revenue_cents"] == 29900
    assert b["revenue_cents"] == 9900
    assert a["costs"]["llm"] == pytest.approx(2.00)
    assert b["costs"]["llm"] == pytest.approx(0.10)
    assert a["costs"]["embedding"] == pytest.approx(0.50)
    assert b["costs"]["embedding"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_tenant_cannot_read_platform_finops_or_margin(
    async_client: AsyncClient,
) -> None:
    org = await _trial(async_client)
    await _seed_paid_invoice(org["organization_id"], 29900)
    await _seed_usage(org["organization_id"], llm_cost=1.00, embedding_cost=0.25)
    session = await _owner_session(org["organization_id"])
    tenant = {
        "Authorization": f"Bearer {session}",
        "X-Organization-Id": org["organization_id"],
    }
    summary = await async_client.get(
        "/api/v1/platform/finops/summary", headers=tenant
    )
    assert summary.status_code == 403, summary.text
    assert summary.json().get("error_code") == "platform_admin_required" or (
        summary.json().get("detail", {}) or {}
    ).get("error_code") == "platform_admin_required"

    org_finops = await async_client.get(
        f"/api/v1/platform/finops/organizations/{org['organization_id']}",
        headers=tenant,
    )
    assert org_finops.status_code == 403, org_finops.text

    usage = await async_client.get("/api/v1/billing/usage", headers=tenant)
    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert "gross_margin_pct" not in body
    assert "gross_profit" not in body
    assert "margin" not in body
    costs = body.get("estimated_costs")
    assert costs is not None
    assert set(costs) == {"llm", "embedding", "storage"}
    assert "infra" not in costs
    assert costs["llm"] == pytest.approx(1.00)
    assert costs["embedding"] == pytest.approx(0.25)

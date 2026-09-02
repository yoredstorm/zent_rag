# =============================================================================
# Tenant Self-Service Billing & Invoices v2 (PROMPT 35)
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
            "email": f"inv-{uuid4().hex[:8]}@example.com",
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
        "Idempotency-Key": f"inv-{uuid4().hex}",
    }


@pytest.mark.asyncio
async def test_generate_invoice_with_items_idempotent(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Inv Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    # Upgrade a pro + usage del período anterior.
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        plan_id = (
            await session.execute(text("SELECT id FROM plans WHERE name = 'pro'"))
        ).scalar()
        await session.execute(
            text(
                "UPDATE subscriptions SET plan_id = :pid, status = 'active' "
                "WHERE organization_id = :oid"
            ),
            {"pid": plan_id, "oid": UUID(org["organization_id"])},
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (request_id, event_type, organization_id, "
                "model, status, estimated_cost, actual_cost, cost_tags, created_at) "
                "VALUES (gen_random_uuid(), 'agent_run', :oid, 'gpt-4o-mini', "
                "'completed', 1.5, 1.5, '{}', NOW() - interval '10 days')"
            ),
            {"oid": UUID(org["organization_id"])},
        )
        await session.commit()
    finally:
        await session.close()

    gen = await async_client.post(
        "/api/v1/billing/invoices/generate",
        headers={**_headers(org), "Idempotency-Key": f"inv-g-{uuid4().hex}"},
    )
    assert gen.status_code == 200, gen.text
    invoice = gen.json()
    assert invoice["status"] == "issued"
    assert invoice["invoice_number"].startswith("INV-")
    assert invoice["subtotal_cents"] > 0
    assert invoice["tax_cents"] == round(invoice["subtotal_cents"] * 0.19)
    assert invoice["total_cents"] == invoice["subtotal_cents"] + invoice["tax_cents"]
    kinds = {item["kind"] for item in invoice["items"]}
    assert "subscription" in kinds
    assert "usage" in kinds
    usage_item = next(i for i in invoice["items"] if i["kind"] == "usage")
    assert usage_item["amount_cents"] == 150
    assert usage_item["meta"]["model"] == "gpt-4o-mini"

    # Idempotente: segunda generación devuelve la misma factura.
    gen2 = await async_client.post(
        "/api/v1/billing/invoices/generate",
        headers={**_headers(org), "Idempotency-Key": f"inv-g2-{uuid4().hex}"},
    )
    assert gen2.json()["id"] == invoice["id"]

    listed = await async_client.get("/api/v1/billing/invoices", headers={**_headers(org)})
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["invoices"]) >= 1


@pytest.mark.asyncio
async def test_invoice_csv_and_pdf(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Inv Files Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    gen = await async_client.post(
        "/api/v1/billing/invoices/generate",
        headers={**_headers(org), "Idempotency-Key": f"inv-f-{uuid4().hex}"},
    )
    invoice_id = gen.json()["id"]

    csv_resp = await async_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/csv", headers={**_headers(org)}
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "kind,description" in csv_resp.text
    assert "total_cents" in csv_resp.text

    pdf_resp = await async_client.get(
        f"/api/v1/billing/invoices/{invoice_id}/pdf", headers={**_headers(org)}
    )
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"].startswith("application/pdf")
    assert pdf_resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_billing_profile_upsert(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Inv Profile Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])
    h = _headers(org)

    put = await async_client.put(
        "/api/v1/billing/billing-profile",
        headers=h,
        json={
            "legal_name": "Zent SPA",
            "tax_id": "76.123.456-7",
            "address_line1": "Av. Providencia 123",
            "city": "Santiago",
            "default_payment_method": "sepa",
            "card_last4": "4242",
        },
    )
    assert put.status_code == 200, put.text
    profile = put.json()["profile"]
    assert profile["legal_name"] == "Zent SPA"
    assert profile["tax_id"] == "76.123.456-7"
    assert profile["default_payment_method"] == "sepa"
    assert profile["card_last4"] == "4242"

    get = await async_client.get("/api/v1/billing/billing-profile", headers=h)
    assert get.json()["profile"]["city"] == "Santiago"

    put2 = await async_client.put(
        "/api/v1/billing/billing-profile",
        headers=_headers(org),
        json={"legal_name": "Zent SpA v2"},
    )
    assert put2.json()["profile"]["legal_name"] == "Zent SpA v2"


@pytest.mark.asyncio
async def test_payment_webhook_marks_paid_and_dedupes(async_client: AsyncClient) -> None:
    org = await _create_org(async_client, "Inv Pay Org")
    org["session"] = await _owner_session(async_client, org["organization_id"])

    gen = await async_client.post(
        "/api/v1/billing/invoices/generate",
        headers={**_headers(org), "Idempotency-Key": f"inv-p-{uuid4().hex}"},
    )
    invoice = gen.json()

    # Webhook público (sin auth).
    payload = {
        "type": "payment_intent.succeeded",
        "id": f"evt_{uuid4().hex[:12]}",
        "data": {
            "object": {
                "id": f"pi_{uuid4().hex[:12]}",
                "amount": invoice["total_cents"],
                "currency": "usd",
                "metadata": {"invoice_id": str(invoice["id"])},
            }
        },
    }
    first = await async_client.post("/api/v1/payments/webhook", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed"

    detail = await async_client.get(
        f"/api/v1/billing/invoices/{invoice['id']}", headers={**_headers(org)}
    )
    assert detail.json()["status"] == "paid"
    assert detail.json()["paid_at"] is not None
    assert detail.json()["payment_intent_id"] is not None

    # Dedupe: mismo provider_event_id → duplicate, sin doble evento.
    second = await async_client.post("/api/v1/payments/webhook", json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"

    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM payment_events "
                    "WHERE provider_event_id = :pid"
                ),
                {"pid": payload["data"]["object"]["id"]},
            )
        ).scalar()
        inv_status = (
            await session.execute(
                text("SELECT status FROM invoices WHERE id = :iid"),
                {"iid": UUID(invoice["id"])},
            )
        ).scalar()
    finally:
        await session.close()
    assert count == 1
    assert inv_status == "paid"

    # Pay simulado (endpoint tenant).
    pay = await async_client.post(
        f"/api/v1/billing/invoices/{invoice['id']}/pay",
        headers={**_headers(org), "Idempotency-Key": f"inv-pay-{uuid4().hex}"},
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["status"] == "paid"

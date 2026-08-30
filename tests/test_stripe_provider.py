# =============================================================================
# Stripe payment provider — signature, checkout, webhook apply
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import text


def _sign(body: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={digest}"


WHSEC = "whsec_test_stripe_secret"
STARTER_PLAN_ID = UUID("10000000-0000-0000-0000-000000000002")


def test_stripe_signature_accepts_valid_payload() -> None:
    from src.infrastructure.billing.stripe_provider import StripePaymentProvider

    body = json.dumps({"id": "evt_1", "type": "ping"}).encode("utf-8")
    header = _sign(body, WHSEC)
    provider = StripePaymentProvider(webhook_secret=WHSEC)
    payload = provider.verify_webhook_signature(
        body, {"stripe-signature": header}
    )
    assert payload is not None
    assert payload["id"] == "evt_1"


def test_stripe_signature_rejects_tampered_body() -> None:
    from src.infrastructure.billing.stripe_provider import StripePaymentProvider

    body = json.dumps({"id": "evt_1", "type": "ping"}).encode("utf-8")
    header = _sign(body, WHSEC)
    tampered = json.dumps({"id": "evt_1", "type": "pwned"}).encode("utf-8")
    provider = StripePaymentProvider(webhook_secret=WHSEC)
    assert (
        provider.verify_webhook_signature(
            tampered, {"Stripe-Signature": header}
        )
        is None
    )


def test_stripe_signature_rejects_missing_header() -> None:
    from src.infrastructure.billing.stripe_provider import StripePaymentProvider

    provider = StripePaymentProvider(webhook_secret=WHSEC)
    assert provider.verify_webhook_signature(b'{"id":"x"}', {}) is None


async def _trial(client: AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/billing/subscription/create-trial",
        json={
            "company_name": f"Stripe Co {uuid4().hex[:8]}",
            "email": f"stripe-{uuid4().hex[:8]}@example.com",
            "country": "CL",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _owner_session(organization_id: str) -> str:
    from src.infrastructure.postgres.relational_db import PostgresUserRepository
    from src.platform.auth.session import encrypt_session

    user = await PostgresUserRepository().get_by_external_id(
        UUID(organization_id), "default-admin"
    )
    assert user is not None
    return encrypt_session(user.id, UUID(organization_id))


@pytest.fixture
def stripe_settings(monkeypatch: pytest.MonkeyPatch):
    from src.core.config import get_settings
    from src.infrastructure.billing.provider import reset_payment_provider

    settings = get_settings()
    monkeypatch.setattr(settings, "PAYMENT_PROVIDER", "stripe")
    monkeypatch.setattr(
        settings, "BILLING_STRIPE_WEBHOOK_SECRET", SecretStr(WHSEC)
    )
    monkeypatch.setattr(
        settings, "BILLING_STRIPE_SECRET_KEY", SecretStr("sk_test_fake")
    )
    monkeypatch.setattr(settings, "SELF_SERVICE_UPGRADE_ENABLED", True)
    reset_payment_provider()
    yield settings
    reset_payment_provider()


async def _seed_starter_price() -> None:
    from src.infrastructure.billing.stripe_provider import (
        ensure_plan_provider_prices_schema,
    )
    from src.infrastructure.postgres.session import get_async_session

    await ensure_plan_provider_prices_schema()
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO plan_provider_prices "
                "(plan_id, interval, provider, price_id) "
                "VALUES (:pid, 'monthly', 'stripe', 'price_starter_month') "
                "ON CONFLICT (plan_id, interval, provider) DO UPDATE "
                "SET price_id = EXCLUDED.price_id"
            ),
            {"pid": STARTER_PLAN_ID},
        )
        await session.commit()
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_checkout_does_not_change_plan_until_webhook(
    async_client: AsyncClient, stripe_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.infrastructure.billing.stripe_provider import StripePaymentProvider

    async def fake_post(self, path: str, form: dict[str, str]) -> dict:
        assert path == "/checkout/sessions"
        return {
            "id": "cs_test_checkout_1",
            "url": "https://checkout.stripe.com/c/pay/cs_test_checkout_1",
        }

    monkeypatch.setattr(StripePaymentProvider, "_post", fake_post)
    await _seed_starter_price()
    org = await _trial(async_client)
    token = await _owner_session(org["organization_id"])
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": org["organization_id"],
    }
    before = await async_client.get("/api/v1/billing/subscription", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["plan_name"] == "trial"

    checkout = await async_client.post(
        "/api/v1/billing/checkout",
        json={"plan_name": "starter", "interval": "monthly"},
        headers=headers,
    )
    assert checkout.status_code == 201, checkout.text
    body = checkout.json()
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert body["session_id"] == "cs_test_checkout_1"

    after = await async_client.get("/api/v1/billing/subscription", headers=headers)
    assert after.json()["plan_name"] == "trial"
    assert after.json()["status"] == "trialing"


@pytest.mark.asyncio
async def test_checkout_session_completed_activates_and_sets_provider_ids(
    async_client: AsyncClient, stripe_settings
) -> None:
    org = await _trial(async_client)
    event = {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_done",
                "client_reference_id": org["organization_id"],
                "customer": "cus_test_1",
                "subscription": "sub_stripe_1",
                "metadata": {
                    "organization_id": org["organization_id"],
                    "plan_name": "starter",
                    "interval": "monthly",
                },
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    header = _sign(raw, WHSEC)
    resp = await async_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "Stripe-Signature": header,
        },
    )
    assert resp.status_code == 200, resp.text
    token = await _owner_session(org["organization_id"])
    sub = await async_client.get(
        "/api/v1/billing/subscription",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert sub.status_code == 200, sub.text
    body = sub.json()
    assert body["plan_name"] == "starter"
    assert body["status"] == "active"
    assert body["payment_provider"] == "stripe"
    assert body["provider_subscription_id"] == "sub_stripe_1"


@pytest.mark.asyncio
async def test_stripe_invoice_paid_replay_does_not_duplicate_payment(
    async_client: AsyncClient, stripe_settings
) -> None:
    org = await _trial(async_client)
    pay_id = f"in_{uuid4().hex[:10]}"
    event = {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": pay_id,
                "customer": "cus_test_1",
                "amount_paid": 4900,
                "currency": "usd",
                "metadata": {"organization_id": org["organization_id"]},
                "parent": {
                    "subscription_details": {
                        "metadata": {"organization_id": org["organization_id"]}
                    }
                },
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    header = _sign(raw, WHSEC)
    first = await async_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    assert first.status_code == 200, first.text
    second = await async_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate"
    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        count = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM payments "
                    "WHERE provider = 'stripe' AND provider_payment_id = :pid"
                ),
                {"pid": pay_id},
            )
        ).scalar()
    finally:
        await session.close()
    assert count == 1


@pytest.mark.asyncio
async def test_stripe_webhook_org_mismatch_does_not_mutate_other_org(
    async_client: AsyncClient, stripe_settings
) -> None:
    org_a = await _trial(async_client)
    org_b = await _trial(async_client)
    event = {
        "id": f"evt_{uuid4().hex[:16]}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_mismatch",
                "client_reference_id": org_b["organization_id"],
                "subscription": "sub_wrong",
                "metadata": {
                    "organization_id": org_a["organization_id"],
                    "plan_name": "starter",
                },
            }
        },
    }
    raw = json.dumps(event).encode("utf-8")
    header = _sign(raw, WHSEC)
    resp = await async_client.post(
        "/api/v1/billing/webhooks/stripe",
        content=raw,
        headers={"Content-Type": "application/json", "Stripe-Signature": header},
    )
    assert resp.status_code == 400, resp.text
    token_b = await _owner_session(org_b["organization_id"])
    sub_b = await async_client.get(
        "/api/v1/billing/subscription",
        headers={
            "Authorization": f"Bearer {token_b}",
            "X-Organization-Id": org_b["organization_id"],
        },
    )
    assert sub_b.json()["plan_name"] == "trial"


@pytest.mark.asyncio
async def test_checkout_rejects_enterprise(
    async_client: AsyncClient, stripe_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.infrastructure.billing.stripe_provider import StripePaymentProvider

    async def fake_post(self, path: str, form: dict[str, str]) -> dict:
        raise AssertionError("should not call Stripe for enterprise")

    monkeypatch.setattr(StripePaymentProvider, "_post", fake_post)
    org = await _trial(async_client)
    token = await _owner_session(org["organization_id"])
    resp = await async_client.post(
        "/api/v1/billing/checkout",
        json={"plan_name": "enterprise", "interval": "monthly"},
        headers={
            "Authorization": f"Bearer {token}",
            "X-Organization-Id": org["organization_id"],
        },
    )
    assert resp.status_code == 409, resp.text

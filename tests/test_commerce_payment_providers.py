# =============================================================================
# Payment provider adapters — Stripe / IZIPAY contract tests
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
import time
from decimal import Decimal

import pytest

from src.platform.commerce.payments.base import SignatureVerificationError
from src.platform.commerce.payments.providers import (
    IzipayPaymentAdapter,
    StripePaymentAdapter,
)

STRIPE_SECRET = "whsec_test_adapter"
IZIPAY_SECRET = "izipay_hash_key"


def _stripe_event(
    *,
    event_type: str,
    payment_status: str | None,
    amount_total: int = 1140,
    currency: str = "pen",
    reference: str = "Z-1",
) -> tuple[bytes, dict[str, str]]:
    obj: dict = {
        "id": "cs_test_1",
        "client_reference_id": reference,
        "metadata": {"order_number": reference},
        "amount_total": amount_total,
        "currency": currency,
    }
    if payment_status is not None:
        obj["payment_status"] = payment_status
    payload = {
        "id": f"evt_{event_type}",
        "type": event_type,
        "created": int(time.time()),
        "data": {"object": obj},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        STRIPE_SECRET.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    return raw, {
        "stripe-signature": f"t={timestamp},v1={signature}",
        "content-type": "application/json",
    }


def _stripe(*, payment_status: str | None = "paid") -> StripePaymentAdapter:
    return StripePaymentAdapter(
        {"secret_key": "sk_test", "webhook_secret": STRIPE_SECRET}, {}
    )


@pytest.mark.parametrize(
    ("provider_type", "payment_status", "expected"),
    [
        ("checkout.session.completed", "paid", "payment.succeeded"),
        ("checkout.session.completed", "no_payment_required", "payment.succeeded"),
        ("checkout.session.completed", "unpaid", "payment.pending"),
        ("checkout.session.completed", None, "payment.pending"),
        ("checkout.session.async_payment_succeeded", "paid", "payment.succeeded"),
        ("checkout.session.async_payment_failed", "unpaid", "payment.failed"),
        ("payment_intent.succeeded", None, "payment.succeeded"),
        ("payment_intent.payment_failed", None, "payment.failed"),
        ("checkout.session.expired", None, "payment.expired"),
    ],
)
def test_stripe_completed_requires_confirmed_funds(
    provider_type: str, payment_status: str | None, expected: str
) -> None:
    raw, headers = _stripe_event(
        event_type=provider_type,
        payment_status=payment_status,
    )
    event = _stripe().verify_webhook(raw, headers)
    assert event.event_type == expected
    assert event.amount == Decimal("11.40")
    assert event.currency == "PEN"
    assert event.reference == "Z-1"


def test_stripe_rejects_bad_signature_and_stale_timestamp() -> None:
    raw, headers = _stripe_event(
        event_type="checkout.session.completed", payment_status="paid"
    )
    bad = dict(headers)
    bad["stripe-signature"] = "t=1,v1=deadbeef"
    with pytest.raises(SignatureVerificationError):
        _stripe().verify_webhook(raw, bad)

    timestamp = int(time.time()) - 1000
    signature = hmac.new(
        STRIPE_SECRET.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    stale = dict(headers)
    stale["stripe-signature"] = f"t={timestamp},v1={signature}"
    with pytest.raises(SignatureVerificationError):
        _stripe().verify_webhook(raw, stale)


def _izipay_event(
    *,
    status: str = "PAID",
    amount: int = 1140,
    currency: str = "PEN",
    reference: str = "Z-1",
    secret: str = IZIPAY_SECRET,
) -> tuple[bytes, dict[str, str]]:
    answer = {
        "orderStatus": status,
        "orderDetails": {"orderId": reference, "creationDate": "2026-10-20T00:00:00Z"},
        "transactions": [
            {"uuid": f"tx-{status}", "amount": amount, "currency": currency}
        ],
    }
    raw_answer = json.dumps(answer, separators=(",", ":"))
    digest = hmac.new(secret.encode(), raw_answer.encode(), hashlib.sha256).hexdigest()
    body = json.dumps(
        {"kr-answer": raw_answer, "kr-hash": digest, "kr-hash-key": "sha256_hmac"}
    ).encode()
    return body, {"content-type": "application/json"}


def _izipay() -> IzipayPaymentAdapter:
    return IzipayPaymentAdapter(
        {"merchant_code": "merchant", "api_key": "api", "hash_key": IZIPAY_SECRET},
        {"mode": "test"},
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PAID", "payment.succeeded"),
        ("AUTHORISED", "payment.succeeded"),
        ("REFUSED", "payment.failed"),
        ("EXPIRED", "payment.expired"),
        ("CANCELLED", "payment.cancelled"),
        ("REFUNDED", "payment.refunded"),
    ],
)
def test_izipay_status_mapping(status: str, expected: str) -> None:
    body, headers = _izipay_event(status=status)
    event = _izipay().verify_webhook(body, headers)
    assert event.event_type == expected
    assert event.provider_event_id == f"tx-{status}"
    assert event.reference == "Z-1"
    assert event.amount == Decimal("11.40")
    assert event.currency == "PEN"


def test_izipay_ipn_uses_api_password_when_hash_kind_missing() -> None:
    """IPN V4 oficial: HMAC hex de kr-answer con PASSWORD de la API."""
    answer = {
        "orderStatus": "PAID",
        "orderDetails": {"orderId": "Z-1"},
        "transactions": [{"uuid": "tx-password", "amount": 1140, "currency": "PEN"}],
    }
    raw_answer = json.dumps(answer, separators=(",", ":"))
    digest = hmac.new(b"api", raw_answer.encode(), hashlib.sha256).hexdigest()
    body = json.dumps({"kr-answer": raw_answer, "kr-hash": digest}).encode()
    event = _izipay().verify_webhook(
        body, {"content-type": "application/json"}
    )
    assert event.event_type == "payment.succeeded"
    assert event.amount == Decimal("11.40")


def test_izipay_rejects_invalid_hash() -> None:
    body, headers = _izipay_event(secret="wrong")
    with pytest.raises(SignatureVerificationError):
        _izipay().verify_webhook(body, headers)

# =============================================================================
# StripePaymentProvider — checkout + Stripe-Signature (no secrets in repo)
# =============================================================================
# Firma: HMAC-SHA256(webhook_secret, f"{t}.{raw_body}") como Stripe.
# Checkout usa httpx hacia api.stripe.com; tests inyectan `http_post`.
# El extra opcional [billing-stripe] documenta la dependencia SDK; el adapter
# no importa `stripe` en el import path para que CI con PAYMENT_PROVIDER=manual
# no lo necesite.
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import httpx

from src.core.config import get_settings
from src.core.ports.payment_provider import CheckoutSession, PaymentProvider
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

HttpPost = Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]]

_STRIPE_API = "https://api.stripe.com/v1"
_SIGNATURE_TOLERANCE_SECONDS = 300


def sign_stripe_webhook(
    payload: dict, secret: str, timestamp: int | None = None
) -> dict[str, str]:
    """Helper de tests: firma un payload como Stripe-Signature."""
    ts = str(int(time.time()) if timestamp is None else timestamp)
    body = json.dumps(payload)
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.".encode("utf-8") + body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Stripe-Signature": f"t={ts},v1={digest}",
        "body": body,
    }


class StripePaymentProvider(PaymentProvider):
    name = "stripe"

    def __init__(
        self,
        *,
        webhook_secret: str | None = None,
        secret_key: str | None = None,
        http_post: HttpPost | None = None,
    ) -> None:
        self._webhook_secret = webhook_secret
        self._secret_key = secret_key
        self._http_post = http_post

    def _whsec(self) -> str:
        if self._webhook_secret:
            return self._webhook_secret
        settings = get_settings()
        secret = settings.BILLING_STRIPE_WEBHOOK_SECRET
        if secret is None:
            return ""
        return secret.get_secret_value()

    def _sk(self) -> str:
        if self._secret_key:
            return self._secret_key
        settings = get_settings()
        key = settings.BILLING_STRIPE_SECRET_KEY
        if key is None:
            return ""
        return key.get_secret_value()

    def verify_webhook_signature(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict | None:
        signature = (
            headers.get("stripe-signature")
            or headers.get("Stripe-Signature")
            or ""
        )
        if not signature:
            return None
        secret = self._whsec()
        if not secret:
            return None
        parts: dict[str, list[str]] = {}
        for item in signature.split(","):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            parts.setdefault(key.strip(), []).append(value.strip())
        timestamps = parts.get("t") or []
        versions = parts.get("v1") or []
        if not timestamps or not versions:
            return None
        timestamp = timestamps[0]
        try:
            if abs(time.time() - int(timestamp)) > _SIGNATURE_TOLERANCE_SECONDS:
                return None
        except ValueError:
            return None
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.".encode("utf-8") + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, provided) for provided in versions):
            return None
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None

    async def create_checkout_session(
        self,
        organization_id: UUID,
        plan_name: str,
        interval: str = "monthly",
    ) -> CheckoutSession:
        price_id = await lookup_stripe_price_id(plan_name, interval)
        if not price_id:
            raise ValueError(
                f"No Stripe price configured for plan '{plan_name}' ({interval})"
            )
        success = get_settings().BILLING_CHECKOUT_SUCCESS_URL
        cancel = get_settings().BILLING_CHECKOUT_CANCEL_URL
        form = {
            "mode": "subscription",
            "success_url": success,
            "cancel_url": cancel,
            "client_reference_id": str(organization_id),
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "metadata[organization_id]": str(organization_id),
            "metadata[plan_name]": plan_name,
            "metadata[interval]": interval,
            "subscription_data[metadata][organization_id]": str(organization_id),
            "subscription_data[metadata][plan_name]": plan_name,
        }
        data = await self._post("/checkout/sessions", form)
        session_id = str(data.get("id") or "")
        url = str(data.get("url") or "")
        if not session_id or not url:
            raise RuntimeError("Stripe checkout session missing id/url")
        return CheckoutSession(session_id=session_id, checkout_url=url)

    async def cancel_subscription(
        self, organization_id: UUID, provider_subscription_id: str | None
    ) -> bool:
        if not provider_subscription_id:
            return True
        await self._post(
            f"/subscriptions/{provider_subscription_id}",
            {"cancel_at_period_end": "true"},
        )
        return True

    async def _post(self, path: str, form: dict[str, str]) -> dict[str, Any]:
        if self._http_post is not None:
            return await self._http_post(path, form)
        key = self._sk()
        if not key:
            raise RuntimeError(
                "Stripe provider requires BILLING_STRIPE_SECRET_KEY "
                "(pip install .[billing-stripe] and PAYMENT_PROVIDER=stripe)"
            )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{_STRIPE_API}{path}",
                data=form,
                auth=(key, ""),
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("Unexpected Stripe response")
            return payload


async def lookup_stripe_price_id(plan_name: str, interval: str) -> str | None:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.billing.entitlements import ensure_entitlements_schema

    await ensure_plan_provider_prices_schema()
    await ensure_entitlements_schema()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT ppp.price_id FROM plan_provider_prices ppp "
                    "JOIN plans p ON p.id = ppp.plan_id "
                    "WHERE p.name = :name AND ppp.interval = :interval "
                    "AND ppp.provider = 'stripe' LIMIT 1"
                ),
                {"name": plan_name, "interval": interval},
            )
        ).fetchone()
    finally:
        await session.close()
    return str(row.price_id) if row else None


_PRICES_SQL = """
CREATE TABLE IF NOT EXISTS plan_provider_prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    interval VARCHAR(10) NOT NULL CHECK (interval IN ('monthly', 'annual')),
    provider VARCHAR(30) NOT NULL,
    price_id VARCHAR(200) NOT NULL,
    UNIQUE (plan_id, interval, provider)
)
"""

_prices_ready = False


async def ensure_plan_provider_prices_schema() -> None:
    global _prices_ready
    if _prices_ready:
        return
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        await session.execute(text(_PRICES_SQL))
        await session.commit()
        _prices_ready = True
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

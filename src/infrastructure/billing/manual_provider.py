# =============================================================================
# ManualPaymentProvider — proveedor manual (dev/trials) con webhook HMAC
# =============================================================================
# Checkout simulado: genera una sesión que el operador "paga" manualmente
# enviando un webhook firmado HMAC-SHA256 (header X-Zent-Signature con
# timestamp.payload y firma). Fuente de verdad: backend + webhook firmado.
#
# Firma: HMAC-SHA256(BILLING_WEBHOOK_SECRET, f"{timestamp}.{body}")
# Header: X-Zent-Signature: t=<timestamp>,v1=<hex>
# =============================================================================
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from uuid import UUID

from src.core.config import get_settings
from src.core.ports.payment_provider import (
    CheckoutSession,
    PaymentProvider,
)


class ManualPaymentProvider(PaymentProvider):
    name = "manual"

    def _secret(self) -> str:
        return get_settings().BILLING_WEBHOOK_SECRET.get_secret_value()

    async def create_checkout_session(
        self,
        organization_id: UUID,
        plan_name: str,
        interval: str = "monthly",
    ) -> CheckoutSession:
        session_id = f"manual_{uuid.uuid4().hex[:16]}"
        return CheckoutSession(
            session_id=session_id,
            checkout_url=f"/billing/checkout/manual/{session_id}",
        )

    def verify_webhook_signature(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict | None:
        signature = headers.get("x-zent-signature") or headers.get(
            "X-Zent-Signature", ""
        )
        if not signature:
            return None
        parts = dict(
            item.split("=", 1)
            for item in signature.split(",")
            if "=" in item
        )
        timestamp = parts.get("t", "")
        provided = parts.get("v1", "")
        if not timestamp or not provided:
            return None

        # Replay window: 5 minutos.
        try:
            if abs(time.time() - int(timestamp)) > 300:
                return None
        except ValueError:
            return None

        expected = hmac.new(
            self._secret().encode("utf-8"),
            f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, provided):
            return None

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None

    async def cancel_subscription(
        self, organization_id: UUID, provider_subscription_id: str | None
    ) -> bool:
        # Provider manual: cancelar es local (no-op externo).
        return True


def sign_manual_webhook(payload: dict, secret: str, timestamp: int | None = None) -> dict[str, str]:
    """Helper para tests/scripts: firma un payload como webhook manual."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    body = json.dumps(payload)
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{ts}.{body}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-Zent-Signature": f"t={ts},v1={signature}",
        "body": body,
    }

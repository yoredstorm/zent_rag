# =============================================================================
# Payments — capacidad de pago independiente del proveedor
# =============================================================================
from __future__ import annotations

from src.platform.commerce.payments.base import (
    CheckoutRequest,
    CheckoutResult,
    NormalizedPaymentEvent,
    PaymentProviderAdapter,
    PaymentProviderError,
    PaymentTimeoutError,
    SignatureVerificationError,
)
from src.platform.commerce.payments.providers import build_adapter
from src.platform.commerce.payments.service import (
    cancel_payment,
    configure_provider,
    create_checkout,
    create_qr,
    ensure_provider,
    ingest_provider_webhook,
    payment_status,
    refund_payment,
)

__all__ = [
    "CheckoutRequest",
    "CheckoutResult",
    "NormalizedPaymentEvent",
    "PaymentProviderAdapter",
    "PaymentProviderError",
    "PaymentTimeoutError",
    "SignatureVerificationError",
    "build_adapter",
    "cancel_payment",
    "configure_provider",
    "create_checkout",
    "create_qr",
    "ensure_provider",
    "ingest_provider_webhook",
    "payment_status",
    "refund_payment",
]

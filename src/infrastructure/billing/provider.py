# =============================================================================
# Billing Platform — resolución de PaymentProvider + almacenamiento de datos
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.core.ports.payment_provider import PaymentProvider

_provider: PaymentProvider | None = None


def reset_payment_provider() -> None:
    """Tests: drop cached provider after mutating PAYMENT_PROVIDER."""
    global _provider
    _provider = None


def get_payment_provider() -> PaymentProvider:
    """Instancia única del provider configurado (manual | stripe)."""
    global _provider
    if _provider is None:
        settings = get_settings()
        name = settings.PAYMENT_PROVIDER.strip().lower()
        if name in ("", "manual"):
            from src.infrastructure.billing.manual_provider import (
                ManualPaymentProvider,
            )

            _provider = ManualPaymentProvider()
        elif name == "stripe":
            from src.infrastructure.billing.stripe_provider import (
                StripePaymentProvider,
            )

            _provider = StripePaymentProvider()
        else:
            raise RuntimeError(f"Unknown PAYMENT_PROVIDER: {name}")
    return _provider

# =============================================================================
# Billing Platform — resolución de PaymentProvider + almacenamiento de datos
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.core.ports.payment_provider import PaymentProvider

_provider: PaymentProvider | None = None


def get_payment_provider() -> PaymentProvider:
    """Instancia única del provider configurado (manual hoy, stripe futuro)."""
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
            raise RuntimeError(
                "Stripe provider requires the extra: pip install .[billing-stripe] "
                "and PAYMENT_PROVIDER=stripe with BILLING_STRIPE_SECRET_KEY"
            )
        else:
            raise RuntimeError(f"Unknown PAYMENT_PROVIDER: {name}")
    return _provider

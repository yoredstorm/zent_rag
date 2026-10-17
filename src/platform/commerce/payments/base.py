# =============================================================================
# Payment Capability Contract — contrato INDEPENDIENTE del proveedor
# =============================================================================
# El workflow depende de `payments.checkout.create` y del evento
# `payment.succeeded`. Nunca de Stripe ni de IZIPAY: el binding del tenant
# resuelve el provider y aquí se normaliza su respuesta.
#
# Un webhook externo NUNCA se convierte en señal sin pasar por:
#   verificación de firma → normalización → dedupe → BusinessEvent → signal
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class PaymentProviderError(Exception):
    """Error del proveedor de pagos (código accionable)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SignatureVerificationError(PaymentProviderError):
    def __init__(self, message: str = "firma de webhook inválida") -> None:
        super().__init__("SIGNATURE_INVALID", message)


class PaymentTimeoutError(PaymentProviderError):
    def __init__(self, message: str = "el proveedor de pagos no respondió a tiempo") -> None:
        super().__init__("PROVIDER_TIMEOUT", message)


def to_cents(amount: Any) -> int:
    """Monto → centavos enteros (nunca float suelto en una pasarela)."""
    return int(
        (Decimal(str(amount or 0)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


@dataclass(kw_only=True, frozen=True)
class CheckoutRequest:
    """Datos de creación de checkout. El monto viene de la orden persistida."""

    organization_id: str
    order_id: str
    order_number: str
    amount: Decimal
    currency: str
    idempotency_key: str
    reference: str
    description: str = "Pago de pedido"
    customer: dict[str, Any] = field(default_factory=dict)
    expires_in_seconds: int = 1800
    notification_url: str | None = None
    return_url: str | None = None


@dataclass(kw_only=True, frozen=True)
class CheckoutResult:
    provider: str
    provider_reference: str
    status: str
    checkout_url: str | None = None
    qr_payload: str | None = None
    qr_image_url: str | None = None
    expires_in_seconds: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(kw_only=True, frozen=True)
class NormalizedPaymentEvent:
    """Evento normalizado del proveedor → BusinessEvent → signal."""

    provider: str
    provider_event_id: str
    provider_event_type: str
    event_type: str  # payment.pending | payment.succeeded | payment.failed | ...
    reference: str | None  # nuestra referencia de negocio (order_number)
    provider_reference: str | None
    amount: Decimal | None
    currency: str | None
    status: str | None
    occurred_at: str | None
    signature_mode: str
    raw: dict[str, Any] = field(default_factory=dict)

    def correlation(self) -> dict[str, Any]:
        """Clave de correlación canónica del pago: `payment_reference`.

        Es exactamente la que declara el WAIT del embudo de ventas
        (`payment_reference = order_number`), de modo que el CK del waiter y el
        de la señal coinciden sin heurísticas."""
        if not self.reference:
            return {}
        return {"payment_reference": self.reference}

    def payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_event_id": self.provider_event_id,
            "amount": float(self.amount) if self.amount is not None else None,
            "currency": self.currency,
            "status": self.status,
            "payment_reference": self.reference,
            "occurred_at": self.occurred_at,
        }


class PaymentProviderAdapter:
    """Puerto del proveedor de pagos (BYOC: credenciales del tenant)."""

    name: str = ""
    supports_qr: bool = True

    def __init__(self, secrets: dict[str, Any], config: dict[str, Any] | None = None) -> None:
        self.secrets = dict(secrets or {})
        self.config = dict(config or {})

    # --- operaciones ---------------------------------------------------------
    async def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        raise PaymentProviderError("PROVIDER_NOT_IMPLEMENTED", f"{self.name} sin checkout.create")

    async def get_status(self, reference: str) -> dict[str, Any]:
        raise PaymentProviderError("PROVIDER_NOT_IMPLEMENTED", f"{self.name} sin status.get")

    async def cancel(self, reference: str) -> bool:
        raise PaymentProviderError("PROVIDER_NOT_IMPLEMENTED", f"{self.name} sin cancel")

    async def refund(self, reference: str, amount: Decimal | None = None) -> dict[str, Any]:
        raise PaymentProviderError("PROVIDER_NOT_IMPLEMENTED", f"{self.name} sin refund")

    # --- ingestión de eventos ------------------------------------------------
    def verify_webhook(
        self, raw_body: bytes, headers: dict[str, str]
    ) -> NormalizedPaymentEvent:
        raise PaymentProviderError("PROVIDER_NOT_IMPLEMENTED", f"{self.name} sin webhook")

    # --- health ---------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ready": bool(self.secrets),
            "missing_credentials": [
                key for key in self.required_secrets if not self.secrets.get(key)
            ],
            "mode": self.config.get("mode") or "test",
        }

    required_secrets: tuple[str, ...] = ()

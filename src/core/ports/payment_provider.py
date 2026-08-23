# =============================================================================
# PaymentProvider — puerto de proveedor de pagos (adapter)
# =============================================================================
# El dominio de billing NUNCA depende de un proveedor concreto. Los
# proveedores implementan este puerto (manual hoy, Stripe mañana vía
# extra opcional). El composition root elige el provider por setting.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(kw_only=True, frozen=True)
class CheckoutSession:
    """Sesión de pago iniciada por el proveedor."""

    session_id: str
    checkout_url: str
    currency: str = "USD"


@dataclass(kw_only=True, frozen=True)
class VerifiedWebhookEvent:
    """Evento de webhook con firma verificada por el proveedor."""

    provider: str
    event_id: str
    event_type: str
    organization_id: UUID | None
    payload: dict


class PaymentProvider(ABC):
    """Contrato de proveedor de pagos."""

    name: str = ""

    @abstractmethod
    async def create_checkout_session(
        self,
        organization_id: UUID,
        plan_name: str,
        interval: str = "monthly",
    ) -> CheckoutSession: ...

    @abstractmethod
    def verify_webhook_signature(
        self,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict | None:
        """Verifica la firma del webhook. Retorna el payload si es válida,
        None si no. Nunca lanza (la ruta responde 400)."""

    @abstractmethod
    async def cancel_subscription(
        self, organization_id: UUID, provider_subscription_id: str | None
    ) -> bool: ...

# =============================================================================
# Webhook de pagos (stripe-like) — público, dedupe por provider_event_id.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/payments", tags=["Payments Webhook"])


class PaymentWebhookIn(BaseModel):
    type: str = Field(..., max_length=120)
    id: str | None = Field(default=None, max_length=200)
    data: dict = Field(default_factory=dict)


@router.post("/webhook", summary="Webhook de pago (stripe-like)")
async def payment_webhook(body: PaymentWebhookIn, request: Request):
    from src.platform.billing.invoices import handle_payment_webhook

    try:
        result = await handle_payment_webhook(body.model_dump())
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Payment webhook failed", error=str(exc)[:200])
        raise HTTPException(500, "Webhook processing failed") from exc

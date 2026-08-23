# =============================================================================
# Billing Webhook Route — endpoint público con firma verificada
# =============================================================================
# POST /api/v1/billing/webhooks/{provider}
# Público (sin auth tenant): la ÚNICA protección es la firma del provider.
# Idempotente por event_id del proveedor.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.infrastructure.observability.logging_config import get_logger
from src.platform.billing.webhooks import (
    UnknownProviderError,
    WebhookSignatureError,
    process_webhook,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["Billing Webhooks"])


def _billing_service():
    from src.infrastructure.postgres.relational_db import (
        PostgresApiKeyRepository,
        PostgresBillingRepository,
    )
    from src.platform.billing.service import BillingService

    return BillingService(
        PostgresBillingRepository(), PostgresApiKeyRepository()
    )


@router.post("/webhooks/{provider}", summary="Webhook de billing (firmado)")
async def billing_webhook(provider: str, request: Request):
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}

    try:
        result = await process_webhook(
            provider, raw_body, headers, _billing_service()
        )
    except WebhookSignatureError as exc:
        logger.warning("Billing webhook rejected", provider=provider)
        raise HTTPException(400, str(exc)) from None
    except UnknownProviderError as exc:
        raise HTTPException(404, str(exc)) from None

    if result["status"] == "error":
        raise HTTPException(
            500,
            f"Webhook processing failed: {result.get('error', 'unknown')}",
        )
    return result

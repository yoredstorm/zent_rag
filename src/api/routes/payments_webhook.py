# =============================================================================
# Webhook legacy de facturación — DESACTIVADO.
# =============================================================================
# Esta ruta aceptaba `payment_intent.succeeded` sin firma y podía marcar una
# factura como pagada. Se conserva solo para responder 410 a integraciones
# antiguas; los pagos reales entran por:
#   POST /api/v1/billing/webhooks/{provider}   (firma verificada)
# o por los webhooks comerciales con tenant/checkout asociados.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/payments", tags=["Payments Webhook"])


@router.post("/webhook", summary="Webhook legacy desactivado")
async def payment_webhook() -> None:
    logger.warning("legacy unsigned payment webhook rejected")
    raise HTTPException(
        410,
        {
            "error_code": "LEGACY_WEBHOOK_DISABLED",
            "message": (
                "El webhook legacy sin firma está desactivado. Usa el webhook "
                "firmado del proveedor o el flujo de checkout del tenant."
            ),
        },
    )

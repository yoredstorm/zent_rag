# =============================================================================
# Billing Webhooks — firma verificada + idempotencia + mapeo de eventos
# =============================================================================
# La fuente de verdad es backend + webhook firmado. NUNCA se confía en el
# frontend para estados de billing.
#   - Firma: cada provider implementa verify_webhook_signature (manual:
#     HMAC-SHA256; stripe futuro: Stripe-Signature).
#   - Idempotencia: billing_events UNIQUE(provider, event_id). Un replay
#     del mismo evento NO reprocesa.
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.billing.provider import get_payment_provider
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.billing import invoices as invoice_store
from src.platform.billing.service import BillingService

logger = get_logger(__name__)

_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS billing_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider VARCHAR(30) NOT NULL,
    event_id VARCHAR(200) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    organization_id UUID,
    payload JSONB NOT NULL DEFAULT '{}',
    processed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, event_id)
)
"""


class WebhookSignatureError(Exception):
    """Firma inválida o ausente."""


class UnknownProviderError(Exception):
    """Provider de webhook desconocido."""


async def ensure_billing_events_table() -> None:
    session = await get_async_session()
    try:
        await session.execute(text(_EVENTS_TABLE))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def _already_processed(provider: str, event_id: str) -> bool:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id FROM billing_events "
                    "WHERE provider = :prov AND event_id = :eid"
                ),
                {"prov": provider, "eid": event_id},
            )
        ).fetchone()
        return row is not None
    finally:
        await session.close()


async def _record_event(
    provider: str,
    event_id: str,
    event_type: str,
    organization_id: UUID | None,
    payload: dict,
    error: str | None = None,
) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO billing_events "
                "(provider, event_id, event_type, organization_id, payload, "
                "processed_at, error) "
                "VALUES (:prov, :eid, :etype, :org, CAST(:payload AS jsonb), "
                "CASE WHEN CAST(:error AS text) IS NULL THEN NOW() "
                "ELSE NULL END, CAST(:error AS text)) "
                "ON CONFLICT (provider, event_id) DO NOTHING"
            ),
            {
                "prov": provider,
                "eid": event_id,
                "etype": event_type,
                "org": organization_id,
                "payload": json.dumps(payload),
                "error": error,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


def _subscription_id(payload: dict) -> UUID | None:
    raw = payload.get("subscription_id") or (payload.get("data") or {}).get(
        "subscription_id"
    )
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _organization_id(payload: dict) -> UUID | None:
    raw = payload.get("organization_id") or (payload.get("data") or {}).get(
        "organization_id"
    )
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


async def process_webhook(
    provider_name: str,
    raw_body: bytes,
    headers: dict[str, str],
    billing: BillingService,
) -> dict:
    """Procesa un webhook firmado. Retorna resumen. Idempotente."""
    await ensure_billing_events_table()
    provider = get_payment_provider()
    if provider.name != provider_name:
        raise UnknownProviderError(
            f"Unknown billing webhook provider: {provider_name}"
        )

    payload = provider.verify_webhook_signature(raw_body, headers)
    if payload is None:
        raise WebhookSignatureError("Invalid webhook signature")

    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("type") or "")
    if not event_id or not event_type:
        raise WebhookSignatureError("Webhook payload missing id/type")

    organization_id = _organization_id(payload)
    subscription_id = _subscription_id(payload)

    if await _already_processed(provider_name, event_id):
        logger.info(
            "Webhook replay ignored (idempotent)",
            provider=provider_name,
            event_id=event_id,
        )
        return {"status": "duplicate", "event_id": event_id}

    try:
        await _dispatch(
            billing, event_type, payload, organization_id, subscription_id
        )
    except Exception as exc:
        await _record_event(
            provider_name, event_id, event_type, organization_id, payload,
            error=str(exc),
        )
        logger.error(
            "Webhook processing failed",
            event_id=event_id,
            event_type=event_type,
            error=str(exc),
        )
        return {"status": "error", "event_id": event_id, "error": str(exc)}

    await _record_event(
        provider_name, event_id, event_type, organization_id, payload
    )
    return {"status": "processed", "event_id": event_id, "type": event_type}


async def _dispatch(
    billing: BillingService,
    event_type: str,
    payload: dict,
    organization_id: UUID | None,
    subscription_id: UUID | None,
) -> None:
    data = payload.get("data") or {}
    provider = get_payment_provider().name

    if event_type == "subscription_created":
        if subscription_id is not None:
            target = str(data.get("status") or "active")
            await billing.transition_status(subscription_id, target)

    elif event_type == "subscription_updated":
        if subscription_id is not None and data.get("status"):
            await billing.transition_status(
                subscription_id, str(data["status"])
            )

    elif event_type == "subscription_canceled":
        if subscription_id is not None:
            await billing.transition_status(subscription_id, "canceled")

    elif event_type == "payment_succeeded":
        if subscription_id is not None:
            await billing.handle_payment_succeeded(subscription_id)
        if organization_id is not None:
            await invoice_store.record_payment(
                organization_id=organization_id,
                provider=provider,
                provider_payment_id=str(
                    data.get("payment_id") or payload.get("id") or ""
                ),
                amount_cents=int(data.get("amount_cents") or 0),
                currency=str(data.get("currency") or "USD"),
                status="succeeded",
            )

    elif event_type == "payment_failed":
        if subscription_id is not None:
            failures = int(data.get("consecutive_failures") or 1)
            await billing.handle_payment_failed(subscription_id, failures)
        if organization_id is not None:
            await invoice_store.record_payment(
                organization_id=organization_id,
                provider=provider,
                provider_payment_id=str(
                    data.get("payment_id") or payload.get("id") or ""
                ),
                amount_cents=int(data.get("amount_cents") or 0),
                currency=str(data.get("currency") or "USD"),
                status="failed",
            )

    elif event_type == "invoice_created":
        if organization_id is not None:
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            await invoice_store.upsert_invoice(
                organization_id=organization_id,
                period_start=now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
                period_end=now,
                subtotal_cents=int(data.get("subtotal_cents") or 0),
                overage_cents=int(data.get("overage_cents") or 0),
                currency=str(data.get("currency") or "USD"),
                provider=provider,
                provider_invoice_id=str(data.get("invoice_id") or ""),
                status="open",
            )

    elif event_type == "invoice_paid":
        invoice_id = str(data.get("invoice_id") or "")
        if invoice_id:
            await invoice_store.mark_invoice_paid(invoice_id)
        if subscription_id is not None:
            await billing.handle_payment_succeeded(subscription_id)

    else:
        logger.info(
            "Unhandled billing webhook event (recorded only)",
            event_type=event_type,
        )

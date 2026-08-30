# =============================================================================
# Platform Control Center inbox — notify only; never mutates org/subscription.
# =============================================================================
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS platform_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type VARCHAR(80) NOT NULL,
    organization_id UUID,
    title VARCHAR(240) NOT NULL,
    body TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_platform_notifications_unread "
    "ON platform_notifications (created_at DESC) WHERE read_at IS NULL"
)


async def ensure_notifications_schema() -> None:
    session = await get_async_session()
    try:
        await session.execute(text(_DDL))
        await session.execute(text(_INDEX))
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def insert_notification(
    *,
    type: str,
    title: str,
    body: str | None = None,
    organization_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> UUID | None:
    await ensure_notifications_schema()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO platform_notifications "
                    "(type, organization_id, title, body, payload) "
                    "VALUES (:type, :oid, :title, :body, CAST(:payload AS jsonb)) "
                    "RETURNING id"
                ),
                {
                    "type": type,
                    "oid": organization_id,
                    "title": title[:240],
                    "body": body,
                    "payload": json.dumps(payload or {}, default=str),
                },
            )
        ).fetchone()
        await session.commit()
        return UUID(str(row.id)) if row else None
    except Exception as exc:
        await session.rollback()
        logger.warning("platform notification insert failed", error=str(exc))
        return None
    finally:
        await session.close()


async def list_notifications(*, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
    await ensure_notifications_schema()
    cap = max(1, min(limit, 100))
    session = await get_async_session()
    try:
        unread = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS n FROM platform_notifications "
                    "WHERE read_at IS NULL"
                )
            )
        ).scalar() or 0
        rows = (
            await session.execute(
                text(
                    """
                    SELECT n.id, n.type, n.organization_id, n.title, n.body,
                           n.payload, n.created_at, n.read_at,
                           o.company_name, o.name AS org_name
                    FROM platform_notifications n
                    LEFT JOIN organizations o ON o.id = n.organization_id
                    ORDER BY n.created_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": cap},
            )
        ).fetchall()
    finally:
        await session.close()
    items = []
    for row in rows:
        payload = row.payload
        if isinstance(payload, (bytes, bytearray, memoryview)):
            payload = bytes(payload).decode("utf-8")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        items.append(
            {
                "id": str(row.id),
                "type": row.type,
                "organization_id": str(row.organization_id)
                if row.organization_id
                else None,
                "organization_name": row.company_name or row.org_name,
                "title": row.title,
                "body": row.body,
                "payload": payload or {},
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "read_at": row.read_at.isoformat() if row.read_at else None,
            }
        )
    return items, int(unread)


async def mark_notification_read(notification_id: UUID) -> bool:
    await ensure_notifications_schema()
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE platform_notifications SET read_at = NOW() "
                "WHERE id = :id AND read_at IS NULL"
            ),
            {"id": notification_id},
        )
        await session.commit()
        return bool(result.rowcount)
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def notify_org_created(organization_id: UUID, company_name: str | None = None) -> None:
    name = company_name
    if not name:
        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COALESCE(company_name, name) AS label "
                        "FROM organizations WHERE id = :oid"
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
            name = str(row.label) if row and row.label else str(organization_id)
        finally:
            await session.close()
    label = name or str(organization_id)
    await insert_notification(
        type="org.created",
        organization_id=organization_id,
        title=f"Nuevo cliente: {label}",
        body="Alta en trial. Revisar en Clientes. No cambia el acceso al marcar leída.",
        payload={"organization_id": str(organization_id)},
    )


async def notify_invoice_open(
    organization_id: UUID, *, invoice_id: UUID, total_cents: int, status: str
) -> None:
    if status not in ("draft", "open") or total_cents <= 0:
        return
    await insert_notification(
        type="invoice.open",
        organization_id=organization_id,
        title="Factura pendiente de cobro",
        body=f"Hay {total_cents} centavos en estado {status}. Verificar pago manual si no hay Stripe.",
        payload={
            "invoice_id": str(invoice_id),
            "total_cents": total_cents,
            "status": status,
        },
    )


async def notify_manual_payment(
    organization_id: UUID, *, provider: str, amount_cents: int, payment_id: UUID
) -> None:
    if provider != "manual":
        return
    await insert_notification(
        type="payment.manual_review",
        organization_id=organization_id,
        title="Pago manual a revisar",
        body="Se registró un pago sin Stripe. Verificar el cobro en la ficha del cliente.",
        payload={
            "payment_id": str(payment_id),
            "amount_cents": amount_cents,
            "provider": provider,
        },
    )

# =============================================================================
# Tenant Self-Service Billing & Invoices v2 — facturas mensuales con items
# (suscripción + usage por modelo/equipo), perfil de facturación, webhook de
# pago (stripe-like) con reconciliación.
# =============================================================================
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

TAX_RATE = 0.19


async def ensure_billing_tables() -> None:
    """Compat: las tablas de billing las crea alembic (migración 054+)."""
    return None


# ---------------------------------------------------------------------------
# Compat (módulo invoices previo usado por billing/webhooks.py)
# ---------------------------------------------------------------------------
async def record_payment(
    organization_id: UUID,
    provider: str,
    provider_payment_id: str,
    amount_cents: int,
    currency: str = "USD",
    status: str = "succeeded",
) -> None:
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO payment_events (id, organization_id, event_type, "
                    "provider, provider_event_id, amount_cents, currency, status) "
                    "VALUES (gen_random_uuid(), :oid, 'payment.' || :status, :provider, "
                    ":pid, :amt, :cur, :status) "
                    "ON CONFLICT (provider_event_id) DO NOTHING"
                ),
                {
                    "oid": organization_id,
                    "provider": provider[:30],
                    "pid": provider_payment_id[:120],
                    "amt": amount_cents,
                    "cur": currency[:3],
                    "status": status[:20],
                },
            )
            # Compat: registro también en la tabla `payments` (legacy).
            await session.execute(
                text(
                    "INSERT INTO payments (id, organization_id, provider, "
                    "provider_payment_id, amount_cents, currency, status) "
                    "VALUES (gen_random_uuid(), :oid, :provider, :pid, :amt, :cur, :status) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "oid": organization_id,
                    "provider": provider[:30],
                    "pid": provider_payment_id[:120],
                    "amt": amount_cents,
                    "cur": currency[:3],
                    "status": status[:20],
                },
            )
            # Pago manual → notificación de revisión (compat con admin).
            if provider == "manual":
                await session.execute(
                    text(
                        "INSERT INTO platform_notifications (id, type, organization_id, "
                        "title, body, payload) "
                        "VALUES (gen_random_uuid(), 'payment.manual_review', :oid, "
                        "'Pago manual recibido', :body, :payload)"
                    ),
                    {
                        "oid": organization_id,
                        "body": f"Pago manual de ${amount_cents / 100:.2f} requiere revisión",
                        "payload": "{}",
                    },
                )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_payment failed", error=str(exc)[:150])


async def upsert_invoice(
    organization_id: UUID,
    period_start,
    period_end,
    subtotal_cents: int,
    overage_cents: int = 0,
    currency: str = "USD",
    provider: str | None = None,
    provider_invoice_id: str | None = None,
    status: str = "issued",
) -> dict:
    total_cents = int(subtotal_cents) + int(overage_cents)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO invoices (id, organization_id, invoice_number, period_start, period_end, "
                    "subtotal_cents, overage_cents, total_cents, currency, status, "
                    "payment_provider, provider_invoice_id) "
                    "VALUES (gen_random_uuid(), :oid, "
                    "'INV-' || upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 6)), "
                    ":start, :end, :sub, :over, "
                    ":total, :cur, :status, :provider, :pid) "
                    "ON CONFLICT (organization_id, period_start, period_end) DO UPDATE SET "
                    "subtotal_cents = EXCLUDED.subtotal_cents, "
                    "overage_cents = EXCLUDED.overage_cents, "
                    "total_cents = EXCLUDED.total_cents, status = EXCLUDED.status "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "start": period_start,
                    "end": period_end,
                    "sub": subtotal_cents,
                    "over": overage_cents,
                    "total": total_cents,
                    "cur": currency[:3],
                    "status": status[:20],
                    "provider": (provider or "internal")[:30],
                    "pid": (provider_invoice_id or "")[:120],
                },
            )
        ).fetchone()
        await session.commit()
    finally:
        await session.close()
    return {"id": str(row.id)}


async def mark_invoice_paid(provider_invoice_id: str) -> None:
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE invoices SET status = 'paid', paid_at = NOW() "
                "WHERE provider_invoice_id = :pid OR id = :pid2"
            ),
            {"pid": provider_invoice_id, "pid2": provider_invoice_id},
        )
        await session.commit()
    finally:
        await session.close()


def _period_for(month_offset: int = 1) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    first = today.replace(day=1)
    period_end = first - timedelta(days=1)
    first_prev = period_end.replace(day=1)
    return first_prev, period_end


# ---------------------------------------------------------------------------
# Generación de facturas
# ---------------------------------------------------------------------------
async def _usage_items(organization_id: UUID, period_start: date, period_end: date) -> list[dict]:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT model, SUM(COALESCE(actual_cost, estimated_cost)) AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at::date BETWEEN :start AND :end "
                    "GROUP BY model ORDER BY cost DESC LIMIT 8"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchall()
    finally:
        await session.close()
    items = []
    for row in rows:
        amount = int(round(float(row.cost) * 100))
        if amount <= 0:
            continue
        items.append(
            {
                "kind": "usage",
                "description": f"Uso de modelo {row.model}",
                "quantity": 1,
                "unit_price_cents": amount,
                "amount_cents": amount,
                "meta": {"model": row.model},
            }
        )
    return items


async def generate_invoice(organization_id: UUID, month_offset: int = 1) -> dict:
    """Genera (idempotente) la factura del período anterior. Items:
    suscripción (prorrateada por días) + usage por modelo."""
    period_start, period_end = _period_for(month_offset)
    session = await get_async_session()
    try:
        existing = (
            await session.execute(
                text(
                    "SELECT id FROM invoices WHERE organization_id = :oid "
                    "AND period_start = :start AND period_end = :end"
                ),
                {"oid": organization_id, "start": period_start, "end": period_end},
            )
        ).fetchone()
        if existing is not None:
            return await get_invoice(existing.id)

        sub = (
            await session.execute(
                text(
                    "SELECT p.name, p.price_monthly_cents, p.is_trial, "
                    "s.status FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid AND s.status IN ('trialing', 'active') "
                    "ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()

    items: list[dict] = []
    subtotal = 0
    if sub is not None and not sub.is_trial:
        days = (period_end - period_start).days + 1
        monthly = int(sub.price_monthly_cents or 0)
        prorated = max(int(monthly * days / 30), 1)
        items.append(
            {
                "kind": "subscription",
                "description": f"Plan {sub.name} (prorrateado {days}d)",
                "quantity": 1,
                "unit_price_cents": prorated,
                "amount_cents": prorated,
                "meta": {"plan": sub.name},
            }
        )
        subtotal += prorated
    usage_items = await _usage_items(organization_id, period_start, period_end)
    items.extend(usage_items)
    subtotal += sum(item["amount_cents"] for item in usage_items)
    tax = int(round(subtotal * TAX_RATE))
    total = subtotal + tax
    invoice_number = f"INV-{period_start.strftime('%Y%m')}-{uuid4().hex[:6].upper()}"

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "INSERT INTO invoices (id, organization_id, invoice_number, "
                    "period_start, period_end, status, subtotal_cents, tax_cents, "
                    "total_cents, due_at) "
                    "VALUES (gen_random_uuid(), :oid, :num, :start, :end, 'issued', "
                    ":subtotal, :tax, :total, NOW() + interval '14 days') "
                    "RETURNING id"
                ),
                {
                    "oid": organization_id,
                    "num": invoice_number,
                    "start": period_start,
                    "end": period_end,
                    "subtotal": subtotal,
                    "tax": tax,
                    "total": total,
                },
            )
        ).fetchone()
        for item in items:
            await session.execute(
                text(
                    "INSERT INTO invoice_items (id, invoice_id, kind, description, "
                    "quantity, unit_price_cents, amount_cents, meta) "
                    "VALUES (gen_random_uuid(), :iid, :kind, :desc, :qty, :unit, :amt, :meta)"
                ),
                {
                    "iid": row.id,
                    "kind": item["kind"],
                    "desc": item["description"][:200],
                    "qty": item["quantity"],
                    "unit": item["unit_price_cents"],
                    "amt": item["amount_cents"],
                    "meta": json.dumps(item.get("meta", {})),
                },
            )
        await session.commit()
    finally:
        await session.close()
    return await get_invoice(row.id)


async def get_invoice(invoice_id: UUID) -> dict:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, invoice_number, period_start, period_end, "
                    "status, subtotal_cents, tax_cents, total_cents, currency, due_at, "
                    "issued_at, paid_at, payment_intent_id, billing_address "
                    "FROM invoices WHERE id = :iid"
                ),
                {"iid": invoice_id},
            )
        ).fetchone()
        if row is None:
            return None
        items = (
            await session.execute(
                text(
                    "SELECT id, kind, description, quantity, unit_price_cents, "
                    "amount_cents, meta FROM invoice_items WHERE invoice_id = :iid "
                    "ORDER BY created_at"
                ),
                {"iid": invoice_id},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id),
        "invoice_number": row.invoice_number,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "status": row.status,
        "subtotal_cents": int(row.subtotal_cents),
        "tax_cents": int(row.tax_cents),
        "total_cents": int(row.total_cents),
        "currency": row.currency,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "issued_at": row.issued_at.isoformat() if row.issued_at else None,
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "payment_intent_id": row.payment_intent_id,
        "items": [
            {
                "id": str(i.id),
                "kind": i.kind,
                "description": i.description,
                "quantity": float(i.quantity),
                "unit_price_cents": int(i.unit_price_cents),
                "amount_cents": int(i.amount_cents),
                "meta": i.meta,
            }
            for i in items
        ],
    }


async def list_invoices(organization_id: UUID, limit: int = 50) -> dict:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id, invoice_number, period_start, period_end, status, "
                    "subtotal_cents, tax_cents, total_cents, issued_at, paid_at "
                    "FROM invoices WHERE organization_id = :oid "
                    "ORDER BY period_start DESC LIMIT :limit"
                ),
                {"oid": organization_id, "limit": limit},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "invoices": [
            {
                "id": str(r.id),
                "invoice_number": r.invoice_number,
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "status": r.status,
                "subtotal_cents": int(r.subtotal_cents),
                "tax_cents": int(r.tax_cents),
                "total_cents": int(r.total_cents),
                "issued_at": r.issued_at.isoformat(),
                "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            }
            for r in rows
        ]
    }


async def void_invoice(invoice_id: UUID) -> bool:
    session = await get_async_session()
    try:
        result = await session.execute(
            text(
                "UPDATE invoices SET status = 'void' "
                "WHERE id = :iid AND status IN ('issued', 'draft')"
            ),
            {"iid": invoice_id},
        )
        await session.commit()
        return result.rowcount > 0
    finally:
        await session.close()


async def invoice_csv(invoice_id: UUID) -> str | None:
    invoice = await get_invoice(invoice_id)
    if invoice is None:
        return None
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["kind", "description", "quantity", "unit_price_cents", "amount_cents"])
    for item in invoice["items"]:
        writer.writerow(
            [item["kind"], item["description"], item["quantity"],
             item["unit_price_cents"], item["amount_cents"]]
        )
    writer.writerow([])
    writer.writerow(["subtotal_cents", invoice["subtotal_cents"]])
    writer.writerow(["tax_cents", invoice["tax_cents"]])
    writer.writerow(["total_cents", invoice["total_cents"]])
    return buffer.getvalue()


def _minimal_pdf(title: str, lines: list[str]) -> bytes:
    """PDF mínimo de una página (sin dependencias) con texto plano."""
    content = "\n".join(lines)
    text_obj = f"BT /F1 11 Tf 40 770 Td 14 TL ({title}) Tj T* {content} ET"
    escaped = content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    escaped_lines = "\n".join(f"({line}) Tj T*" for line in lines[:40])
    objects = (
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
        f"4 0 obj << /Length {len(escaped_lines) + 60} >> stream\n"
        "BT /F1 10 Tf 40 800 Td 16 TL\n"
        f"({title}) Tj T*\n"
        f"{escaped_lines}\n"
        "ET\nendstream endobj\n"
        "5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
        "trailer << /Root 1 0 R /Size 6 >>\n%%EOF"
    )
    return b"%PDF-1.4\n" + objects.encode("latin-1", "replace")


async def invoice_pdf(invoice_id: UUID) -> bytes | None:
    invoice = await get_invoice(invoice_id)
    if invoice is None:
        return None
    lines = [
        f"Factura {invoice['invoice_number']}",
        f"Periodo: {invoice['period_start']} al {invoice['period_end']}",
        f"Estado: {invoice['status']}",
        "",
    ]
    for item in invoice["items"]:
        lines.append(f"- {item['description']}: ${item['amount_cents'] / 100:.2f}")
    lines += [
        "",
        f"Subtotal: ${invoice['subtotal_cents'] / 100:.2f}",
        f"Impuestos (19%): ${invoice['tax_cents'] / 100:.2f}",
        f"TOTAL: ${invoice['total_cents'] / 100:.2f} {invoice['currency']}",
    ]
    return _minimal_pdf(f"Zent Invoice {invoice['invoice_number']}", lines)


# ---------------------------------------------------------------------------
# Perfil de facturación
# ---------------------------------------------------------------------------
async def get_billing_profile(organization_id: UUID) -> dict | None:
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT * FROM billing_profiles WHERE organization_id = :oid"),
                {"oid": organization_id},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        return None
    return {
        "organization_id": str(row.organization_id),
        "legal_name": row.legal_name,
        "tax_id": row.tax_id,
        "address_line1": row.address_line1,
        "address_line2": row.address_line2,
        "city": row.city,
        "region": row.region,
        "postal_code": row.postal_code,
        "country": row.country,
        "default_payment_method": row.default_payment_method,
        "card_last4": row.card_last4,
        "updated_at": row.updated_at.isoformat(),
    }


async def upsert_billing_profile(organization_id: UUID, fields: dict) -> dict:
    allowed = {
        "legal_name", "tax_id", "address_line1", "address_line2", "city",
        "region", "postal_code", "country", "default_payment_method", "card_last4",
    }
    present = {k: fields[k] for k in allowed if k in fields and fields[k] is not None}
    sets = [f"{k} = :{k}" for k in present]
    params = {}
    for key, value in present.items():
        params[key] = str(value)[:200]
    params["oid"] = organization_id
    if not sets:
        sets = ["updated_at = NOW()"]
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO billing_profiles (id, organization_id) "
                "VALUES (gen_random_uuid(), :oid) "
                "ON CONFLICT (organization_id) DO NOTHING"
            ),
            {"oid": organization_id},
        )
        await session.execute(
            text(
                f"UPDATE billing_profiles SET {', '.join(sets)}, updated_at = NOW() "
                "WHERE organization_id = :oid"
            ),
            params,
        )
        await session.commit()
    finally:
        await session.close()
    return await get_billing_profile(organization_id)


# ---------------------------------------------------------------------------
# Webhook de pago (stripe-like) + reconciliación
# ---------------------------------------------------------------------------
async def handle_payment_webhook(payload: dict) -> dict:
    """Procesa eventos de pago; dedupe por provider_event_id (UNIQUE)."""
    event_type = payload.get("type", "")
    data = payload.get("data", {})
    obj = data.get("object", {}) if isinstance(data, dict) else {}
    provider_event_id = obj.get("id") or payload.get("id") or uuid4().hex
    amount = int(obj.get("amount", 0) or 0)
    currency = (obj.get("currency") or "usd").upper()[:3]
    invoice_id_raw = obj.get("metadata", {}).get("invoice_id") or obj.get("invoice_id")
    organization_raw = obj.get("metadata", {}).get("organization_id")

    session = await get_async_session()
    try:
        already = (
            await session.execute(
                text("SELECT 1 FROM payment_events WHERE provider_event_id = :pid"),
                {"pid": provider_event_id},
            )
        ).fetchone()
        if already:
            return {"status": "duplicate", "event_type": event_type}

        invoice_id = None
        organization_id = None
        if invoice_id_raw:
            try:
                invoice_id = UUID(str(invoice_id_raw))
            except ValueError:
                invoice_id = None
        if organization_raw:
            try:
                organization_id = UUID(str(organization_raw))
            except ValueError:
                organization_id = None

        if invoice_id is not None and organization_id is None:
            inv = (
                await session.execute(
                    text("SELECT organization_id FROM invoices WHERE id = :iid"),
                    {"iid": invoice_id},
                )
            ).fetchone()
            organization_id = inv.organization_id if inv else None

        if event_type in ("payment_intent.succeeded", "invoice.paid") and invoice_id is not None:
            await session.execute(
                text(
                    "UPDATE invoices SET status = 'paid', paid_at = NOW(), "
                    "payment_provider = 'stripe', payment_intent_id = :pid "
                    "WHERE id = :iid AND status <> 'paid'"
                ),
                {"pid": obj.get("payment_intent") or provider_event_id, "iid": invoice_id},
            )
            if organization_id is not None:
                try:
                    from src.platform.notifyv2.notifications import notify

                    await notify(
                        organization_id,
                        "invoice.paid",
                        "Factura pagada",
                        f"Factura {str(invoice_id)[:8]} confirmada",
                        {"invoice_id": str(invoice_id)},
                    )
                except Exception:  # noqa: BLE001
                    pass
        status = "succeeded" if "succeeded" in event_type else "received"
        await session.execute(
            text(
                "INSERT INTO payment_events (id, organization_id, invoice_id, event_type, "
                "provider, provider_event_id, amount_cents, currency, status) "
                "VALUES (gen_random_uuid(), :oid, :iid, :etype, 'stripe', :pid, :amt, :cur, :st)"
            ),
            {
                "oid": organization_id,
                "iid": invoice_id,
                "etype": event_type[:60],
                "pid": provider_event_id,
                "amt": amount,
                "cur": currency,
                "st": status,
            },
        )
        await session.commit()
    finally:
        await session.close()
    return {"status": "processed", "event_type": event_type}


async def reconciliation_status(organization_id: UUID | None = None) -> dict:
    session = await get_async_session()
    try:
        params: dict = {}
        where = ""
        if organization_id:
            where = " WHERE organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT status, COUNT(*) AS total, "
                    "COALESCE(SUM(total_cents), 0) AS cents "
                    "FROM invoices" + where + " GROUP BY status ORDER BY status"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "by_status": [
            {"status": r.status, "count": int(r.total), "cents": int(r.cents)}
            for r in rows
        ]
    }

# =============================================================================
# Billing Reconciliation — usage vs invoices vs payments
# =============================================================================
# Report-only: compara el costo de uso (usage_events) contra lo facturado
# (invoices) y lo pagado (payments). Detecta: uso sin facturar, facturas
# impagas, pagos sin factura y sobre-facturación.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.billing.invoices import ensure_billing_tables
from src.platform.usage.usage_engine import ensure_usage_table


async def reconcile(
    organization_id: UUID | None = None, *, days: int = 30
) -> list[dict]:
    """Reporte por organization. days = ventana de análisis de usage."""
    await ensure_billing_tables()
    await ensure_usage_table()
    days = max(1, min(days, 365))

    session = await get_async_session()
    try:
        org_filter = "AND organization_id = :org" if organization_id else ""
        params: dict = {"days": str(days)}
        if organization_id:
            params["org"] = organization_id

        usage_rows = (
            await session.execute(
                text(
                    "SELECT organization_id, "
                    "COALESCE(SUM(estimated_cost), 0) AS usage_cost, "
                    "COUNT(*)::int AS requests, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens "
                    "FROM usage_events "
                    "WHERE created_at >= NOW() - (:days || ' days')::interval "
                    + org_filter
                    + " GROUP BY organization_id"
                ),
                params,
            )
        ).fetchall()
        invoice_rows = (
            await session.execute(
                text(
                    "SELECT organization_id, "
                    "COALESCE(SUM(total_cents), 0)::bigint AS invoiced_cents, "
                    "COALESCE(SUM(total_cents) FILTER "
                    "(WHERE status NOT IN ('paid','void')), 0)::bigint "
                    "AS unpaid_cents, COUNT(*)::int AS invoices "
                    "FROM invoices "
                    "WHERE period_start >= NOW() - (:days || ' days')::interval "
                    + org_filter
                    + " GROUP BY organization_id"
                ),
                params,
            )
        ).fetchall()
        payment_rows = (
            await session.execute(
                text(
                    "SELECT organization_id, "
                    "COALESCE(SUM(amount_cents) FILTER "
                    "(WHERE status = 'succeeded'), 0)::bigint AS paid_cents, "
                    "COALESCE(SUM(amount_cents) FILTER "
                    "(WHERE invoice_id IS NULL), 0)::bigint "
                    "AS unmatched_cents "
                    "FROM payments "
                    "WHERE created_at >= NOW() - (:days || ' days')::interval "
                    + org_filter
                    + " GROUP BY organization_id"
                ),
                params,
            )
        ).fetchall()

        usage_by_org = {r.organization_id: r for r in usage_rows}
        invoice_by_org = {r.organization_id: r for r in invoice_rows}
        payment_by_org = {r.organization_id: r for r in payment_rows}

        orgs = set(usage_by_org) | set(invoice_by_org) | set(payment_by_org)
        report: list[dict] = []
        for org in sorted(orgs, key=str):
            u = usage_by_org.get(org)
            inv = invoice_by_org.get(org)
            pay = payment_by_org.get(org)
            usage_cost = float(u.usage_cost) if u else 0.0
            invoiced = float(inv.invoiced_cents or 0) / 100 if inv else 0.0
            paid = float(pay.paid_cents or 0) / 100 if pay else 0.0
            unpaid = float(inv.unpaid_cents or 0) / 100 if inv else 0.0
            unmatched = float(pay.unmatched_cents or 0) / 100 if pay else 0.0
            report.append(
                {
                    "organization_id": str(org),
                    "requests": int(u.requests) if u else 0,
                    "tokens": int(u.tokens) if u else 0,
                    "usage_cost": round(usage_cost, 8),
                    "invoiced": round(invoiced, 2),
                    "paid": round(paid, 2),
                    "unpaid": round(unpaid, 2),
                    "unmatched_payments": round(unmatched, 2),
                    "delta_usage_vs_invoiced": round(usage_cost - invoiced, 2),
                    "delta_invoiced_vs_paid": round(invoiced - paid, 2),
                }
            )
        return report
    finally:
        await session.close()

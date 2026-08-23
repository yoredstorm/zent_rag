# =============================================================================
# Billing Invoice Job — genera facturas del ciclo con overage desde usage
# =============================================================================
# Uso mensual (cron / manual):
#   python src/scripts/billing_invoice.py [--days 30] [--dry-run]
#
# Para cada organización con suscripción activa/trialing:
#   - subtotal: precio mensual del plan (0 para trial)
#   - overage: uso por encima de included × precios del plan
#     (requests, tokens, storage, connectors, agents)
#   - invoice idempotente por (organization_id, periodo)
#
# Nota: overage de connectors/agents usa conteo actual (aproximación
# mensual; el conteo histórico exacto requiere contadores dedicados).
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.postgres.session import get_async_session
from src.platform.billing.invoices import ensure_billing_tables, upsert_invoice
from src.platform.usage.usage_engine import ensure_usage_table

GB = 1024 ** 3


async def _plan_overage(plan_row) -> dict:
    return {
        "subtotal_cents": int(plan_row.price_monthly_cents or 0),
        "included_requests": int(plan_row.requests_per_month or 0),
        "included_tokens": int(plan_row.tokens_per_month or 0) if plan_row.tokens_per_month else None,
        "included_storage": int(plan_row.included_storage) if plan_row.included_storage else None,
        "max_agents": int(plan_row.max_agents) if plan_row.max_agents else None,
        "max_connectors": int(plan_row.max_connectors) if plan_row.max_connectors else None,
        "overage_request_cost_per_1k": float(plan_row.overage_request_cost_per_1k or 0),
        "overage_token_cost_per_1k": float(plan_row.overage_token_cost_per_1k or 0),
        "overage_storage_cost_per_gb": float(plan_row.overage_storage_cost_per_gb or 0),
        "overage_connector_monthly_cents": float(plan_row.overage_connector_monthly_cents or 0),
        "overage_agent_monthly_cents": float(plan_row.overage_agent_monthly_cents or 0),
    }


async def _usage_window(organization_id: UUID, days: int) -> dict:
    await ensure_usage_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS requests, "
                    "COALESCE(SUM(total_tokens), 0)::bigint AS tokens, "
                    "COALESCE(SUM(estimated_cost), 0)::float AS cost "
                    "FROM usage_events "
                    "WHERE organization_id = :org "
                    "AND created_at >= NOW() - (:days || ' days')::interval"
                ),
                {"org": organization_id, "days": str(days)},
            )
        ).fetchone()
        if row is None:
            return {"requests": 0, "tokens": 0, "cost": 0.0}
        return {
            "requests": int(row.requests or 0),
            "tokens": int(row.tokens or 0),
            "cost": float(row.cost or 0.0),
        }
    finally:
        await session.close()


async def _resource_counts(organization_id: UUID) -> dict:
    session = await get_async_session()
    try:
        agents = (
            await session.execute(
                text("SELECT COUNT(*) FROM agents WHERE organization_id = :org"),
                {"org": organization_id},
            )
        ).scalar()
        connectors = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM connectors WHERE organization_id = :org"
                ),
                {"org": organization_id},
            )
        ).scalar()
        return {"agents": int(agents or 0), "connectors": int(connectors or 0)}
    finally:
        await session.close()


async def run_invoice_job(days: int = 30, dry_run: bool = False) -> dict:
    await ensure_billing_tables()
    now = datetime.now(timezone.utc)
    period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    session = await get_async_session()
    try:
        subs = (
            await session.execute(
                text(
                    "SELECT s.id AS subscription_id, s.organization_id, "
                    "p.price_monthly_cents, p.requests_per_month, "
                    "p.tokens_per_month, p.included_storage, p.max_agents, "
                    "p.max_connectors, p.overage_request_cost_per_1k, "
                    "p.overage_token_cost_per_1k, "
                    "p.overage_storage_cost_per_gb, "
                    "p.overage_connector_monthly_cents, "
                    "p.overage_agent_monthly_cents, p.name AS plan_name "
                    "FROM subscriptions s JOIN plans p ON s.plan_id = p.id "
                    "WHERE s.status IN ('active','trialing')"
                )
            )
        ).fetchall()
    finally:
        await session.close()

    created = 0
    skipped = 0
    for sub in subs:
        overage = await _plan_overage(sub)
        usage = await _usage_window(sub.organization_id, days)
        resources = await _resource_counts(sub.organization_id)

        subtotal = overage["subtotal_cents"]
        overage_cents = 0
        if overage["included_tokens"] is not None:
            extra_tokens = max(usage["tokens"] - overage["included_tokens"], 0)
            overage_cents += int(
                extra_tokens / 1000 * overage["overage_token_cost_per_1k"] * 100
            )
        extra_requests = max(
            usage["requests"] - overage["included_requests"], 0
        )
        overage_cents += int(
            extra_requests / 1000
            * overage["overage_request_cost_per_1k"]
            * 100
        )
        if overage["included_storage"] is not None:
            extra_storage = max(usage["cost"], 0)  # proxy conservador
            overage_cents += int(extra_storage)  # costo real ya medido
        if overage["max_agents"] is not None:
            extra_agents = max(resources["agents"] - overage["max_agents"], 0)
            overage_cents += int(
                extra_agents * overage["overage_agent_monthly_cents"]
            )
        if overage["max_connectors"] is not None:
            extra_connectors = max(
                resources["connectors"] - overage["max_connectors"], 0
            )
            overage_cents += int(
                extra_connectors * overage["overage_connector_monthly_cents"]
            )

        if dry_run:
            created += 1
            print(
                f"DRY-RUN {sub.plan_name} org={sub.organization_id} "
                f"subtotal={subtotal} overage={overage_cents}"
            )
            continue

        await upsert_invoice(
            organization_id=sub.organization_id,
            period_start=period_start,
            period_end=now,
            subtotal_cents=subtotal,
            overage_cents=overage_cents,
            status="open" if (subtotal + overage_cents) > 0 else "paid",
        )
        created += 1

    return {"created": created, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate monthly billing invoices")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(run_invoice_job(args.days, args.dry_run))
    print(result)


if __name__ == "__main__":
    main()

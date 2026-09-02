# =============================================================================
# Revenue Intelligence & ARR — ARR/MRR por plan, expansión/contracción,
# cohortes trial→paid con funnels, forecast y export CSV.
# =============================================================================
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def record_sub_event(
    subscription_id: UUID | None,
    organization_id: UUID,
    event_type: str,
    plan_name: str | None,
    mrr_cents: int = 0,
    from_plan_id: UUID | None = None,
    to_plan_id: UUID | None = None,
) -> None:
    try:
        session = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO subscription_events (id, subscription_id, "
                    "organization_id, event_type, plan_name, mrr_cents, "
                    "from_plan_id, to_plan_id) "
                    "VALUES (gen_random_uuid(), :sid, :oid, :etype, :plan, :mrr, "
                    ":fpid, :tpid)"
                ),
                {
                    "sid": subscription_id,
                    "oid": organization_id,
                    "etype": event_type[:30],
                    "plan": plan_name,
                    "mrr": mrr_cents,
                    "fpid": from_plan_id,
                    "tpid": to_plan_id,
                },
            )
            await session.commit()
        finally:
            await session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Sub event record failed", error=str(exc)[:150])


# ---------------------------------------------------------------------------
# ARR / MRR por plan
# ---------------------------------------------------------------------------
async def revenue_summary(days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT p.name AS plan, p.is_trial, "
                    "COUNT(*) AS subscribers, "
                    "SUM(CASE WHEN p.is_trial THEN 0 ELSE p.price_monthly_cents END) AS mrr_cents "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.status IN ('trialing', 'active') "
                    "GROUP BY p.name, p.is_trial ORDER BY mrr_cents DESC NULLS LAST"
                )
            )
        ).fetchall()
        trials_total = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM subscriptions "
                    "WHERE status = 'trialing' AND created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        churned = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM subscriptions "
                    "WHERE status IN ('canceled', 'expired') AND created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        started = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM subscriptions WHERE created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        expansion = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(mrr_cents), 0) FROM subscription_events "
                    "WHERE event_type = 'upgraded' AND created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        contraction = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(mrr_cents), 0) FROM subscription_events "
                    "WHERE event_type = 'downgraded' AND created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
        churned_mrr = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(mrr_cents), 0) FROM subscription_events "
                    "WHERE event_type = 'canceled' AND created_at >= :since"
                ),
                {"since": since},
            )
        ).scalar()
    finally:
        await session.close()

    by_plan = [
        {
            "plan": r.plan,
            "is_trial": bool(r.is_trial),
            "subscribers": int(r.subscribers),
            "mrr_cents": int(r.mrr_cents or 0),
            "arr_cents": int(r.mrr_cents or 0) * 12,
        }
        for r in rows
    ]
    total_mrr = sum(item["mrr_cents"] for item in by_plan)
    return {
        "window_days": days,
        "mrr_cents": total_mrr,
        "arr_cents": total_mrr * 12,
        "by_plan": by_plan,
        "trials_created": int(trials_total),
        "subscribers_started": int(started),
        "churned_subscribers": int(churned),
        "churn_rate": round(int(churned) / int(started), 4) if started else 0.0,
        "expansion_mrr_cents": int(expansion),
        "contraction_mrr_cents": int(contraction),
        "churned_mrr_cents": int(churned_mrr),
        "net_mrr_delta_cents": int(expansion) - int(contraction) - int(churned_mrr),
    }


# ---------------------------------------------------------------------------
# Cohortes trial→paid (funnels)
# ---------------------------------------------------------------------------
async def conversion_funnels(months: int = 12) -> dict:
    session = await get_async_session()
    try:
        cohorts = (
            await session.execute(
                text(
                    "SELECT date_trunc('month', s.created_at) AS cohort, "
                    "COUNT(*) FILTER (WHERE s.status = 'trialing') AS trials, "
                    "COUNT(*) FILTER (WHERE s.status IN ('active') "
                    "AND p.is_trial = false) AS converted, "
                    "COUNT(*) FILTER (WHERE s.status IN ('active', 'trialing')) AS retained "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.created_at >= date_trunc('month', NOW()) - "
                    "make_interval(months => :months) "
                    "GROUP BY cohort ORDER BY cohort"
                ),
                {"months": months},
            )
        ).fetchall()
        # MRR actual de cada cohorte (solo suscripciones de ese mes, hoy).
        cohort_mrr = (
            await session.execute(
                text(
                    "SELECT date_trunc('month', s.created_at) AS cohort, "
                    "SUM(CASE WHEN p.is_trial THEN 0 ELSE p.price_monthly_cents END) AS mrr_cents "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.status IN ('trialing', 'active') "
                    "AND s.created_at >= date_trunc('month', NOW()) - "
                    "make_interval(months => :months) "
                    "GROUP BY cohort ORDER BY cohort"
                ),
                {"months": months},
            )
        ).fetchall()
    finally:
        await session.close()
    mrr_by_cohort = {r.cohort: int(r.mrr_cents or 0) for r in cohort_mrr}
    funnels = [
        {
            "cohort": r.cohort.strftime("%Y-%m"),
            "trials": int(r.trials),
            "converted": int(r.converted),
            "conversion_rate": round(int(r.converted) / int(r.trials), 4) if int(r.trials) else 0.0,
            "retained": int(r.retained),
            "mrr_cents_now": mrr_by_cohort.get(r.cohort, 0),
        }
        for r in cohorts
    ]
    return {"funnels": funnels, "count": len(funnels)}


# ---------------------------------------------------------------------------
# Forecast de revenue
# ---------------------------------------------------------------------------
async def revenue_forecast(months: int = 6) -> dict:
    funnels = (await conversion_funnels(12))["funnels"]
    session = await get_async_session()
    try:
        avg_price = (
            await session.execute(
                text(
                    "SELECT AVG(price_monthly_cents) FROM plans WHERE is_trial = false"
                )
            )
        ).scalar() or 0
        recent_trials = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM subscriptions "
                    "WHERE created_at >= NOW() - interval '3 months'"
                )
            )
        ).scalar()
    finally:
        await session.close()

    # Tendencias: conversión media de los últimos 6 meses y crecimiento de trials.
    recent = funnels[-6:] if len(funnels) >= 6 else funnels
    avg_conversion = (
        sum(f["conversion_rate"] for f in recent) / len(recent) if recent else 0.02
    )
    trial_growth = 1.0
    if len(funnels) >= 2:
        old = sum(f["trials"] for f in funnels[:-1]) / max(len(funnels) - 1, 1)
        new = funnels[-1]["trials"]
        if old > 0:
            trial_growth = max(0.5, min(2.0, new / old))
    monthly_trials = max(int(recent_trials / 3), 1) if recent_trials else 10

    projected = []
    running = int(recent_trials / 3) if recent_trials else 10
    for i in range(1, months + 1):
        running = int(running * trial_growth)
        new_mrr = int(running * avg_conversion * float(avg_price))
        projected.append(
            {
                "month": (datetime.now(timezone.utc).replace(day=1) + timedelta(days=32 * i)).strftime("%Y-%m"),
                "expected_trials": running,
                "expected_conversions": max(int(running * avg_conversion), 1),
                "new_mrr_cents": max(new_mrr, 1),
            }
        )
    summary = (await revenue_summary(30))
    return {
        "current_mrr_cents": summary["mrr_cents"],
        "avg_conversion_rate": round(avg_conversion, 4),
        "trial_growth_rate": round(trial_growth, 2),
        "projected": projected,
    }


# ---------------------------------------------------------------------------
# Ledger y export CSV
# ---------------------------------------------------------------------------
async def list_events(organization_id: UUID | None = None, days: int = 30, limit: int = 200) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    session = await get_async_session()
    try:
        where = "WHERE created_at >= :since"
        params: dict = {"since": since, "limit": limit}
        if organization_id:
            where += " AND organization_id = :oid"
            params["oid"] = organization_id
        rows = (
            await session.execute(
                text(
                    "SELECT id, subscription_id, organization_id, event_type, plan_name, "
                    "mrr_cents, created_at FROM subscription_events "
                    + where
                    + " ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "events": [
            {
                "id": str(r.id),
                "subscription_id": str(r.subscription_id) if r.subscription_id else None,
                "organization_id": str(r.organization_id),
                "event_type": r.event_type,
                "plan_name": r.plan_name,
                "mrr_cents": int(r.mrr_cents or 0),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


async def export_revenue_csv() -> str:
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT o.id AS org_id, o.name AS org_name, p.name AS plan, "
                    "s.status, s.billing_interval, "
                    "CASE WHEN p.is_trial THEN 0 ELSE p.price_monthly_cents END AS mrr_cents, "
                    "s.created_at, s.canceled_at "
                    "FROM subscriptions s "
                    "JOIN organizations o ON o.id = s.organization_id "
                    "JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.status IN ('trialing', 'active', 'canceled', 'expired') "
                    "ORDER BY s.created_at DESC"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["organization_id", "organization_name", "plan", "status", "billing_interval",
         "mrr_cents", "arr_cents", "created_at", "canceled_at"]
    )
    for r in rows:
        writer.writerow(
            [
                str(r.org_id),
                r.org_name,
                r.plan,
                r.status,
                r.billing_interval or "monthly",
                int(r.mrr_cents or 0),
                int(r.mrr_cents or 0) * 12,
                r.created_at.isoformat(),
                r.canceled_at.isoformat() if r.canceled_at else "",
            ]
        )
    return buffer.getvalue()

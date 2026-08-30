# =============================================================================
# FinOps — revenue (paid invoices) vs classified usage + configurable infra
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.postgres.session import get_async_session

# LLM vs embedding: embedding_tokens-only rows, or embed-like models without
# prompt/completion. Uses COALESCE(actual_cost, estimated_cost).
_USAGE_SELECT = """
SELECT
  COALESCE(SUM(CASE WHEN (
    (
      embedding_tokens > 0
      AND COALESCE(prompt_tokens, 0) = 0
      AND COALESCE(completion_tokens, 0) = 0
    )
    OR (
      COALESCE(prompt_tokens, 0) = 0
      AND COALESCE(completion_tokens, 0) = 0
      AND (
        lower(COALESCE(model, '')) LIKE '%embed%'
        OR lower(COALESCE(model, '')) LIKE '%bge%'
        OR lower(COALESCE(model, '')) LIKE '%e5-%'
      )
    )
  ) THEN COALESCE(actual_cost, estimated_cost) ELSE 0 END), 0)::float AS embedding,
  COALESCE(SUM(CASE WHEN (
    (
      embedding_tokens > 0
      AND COALESCE(prompt_tokens, 0) = 0
      AND COALESCE(completion_tokens, 0) = 0
    )
    OR (
      COALESCE(prompt_tokens, 0) = 0
      AND COALESCE(completion_tokens, 0) = 0
      AND (
        lower(COALESCE(model, '')) LIKE '%embed%'
        OR lower(COALESCE(model, '')) LIKE '%bge%'
        OR lower(COALESCE(model, '')) LIKE '%e5-%'
      )
    )
  ) THEN 0 ELSE COALESCE(actual_cost, estimated_cost) END), 0)::float AS llm,
  COUNT(*)::int AS requests
FROM usage_events
"""
_USAGE_SQL_ALL = text(
    _USAGE_SELECT + " WHERE created_at >= :start AND created_at < :end"
)
_USAGE_SQL_ORG = text(
    _USAGE_SELECT
    + " WHERE created_at >= :start AND created_at < :end"
    + " AND organization_id = :oid"
)
_REVENUE_SQL_ALL = text(
    """
    SELECT COALESCE(SUM(total_cents), 0)::bigint AS revenue
    FROM invoices
    WHERE status = 'paid' AND paid_at IS NOT NULL
      AND paid_at >= :start AND paid_at < :end
    """
)
_REVENUE_SQL_ORG = text(
    """
    SELECT COALESCE(SUM(total_cents), 0)::bigint AS revenue
    FROM invoices
    WHERE status = 'paid' AND paid_at IS NOT NULL
      AND paid_at >= :start AND paid_at < :end
      AND organization_id = :oid
    """
)
_MRR_SELECT = """
SELECT COALESCE(SUM(
    CASE
        WHEN s.billing_interval = 'annual'
            THEN (p.price_annual_cents / 12)
        ELSE p.price_monthly_cents
    END
), 0)::int AS mrr_cents
FROM subscriptions s
JOIN plans p ON p.id = s.plan_id
"""
_MRR_SQL_ALL = text(_MRR_SELECT + " WHERE s.status IN ('active', 'trialing')")
_MRR_SQL_ORG = text(
    _MRR_SELECT
    + " WHERE s.status IN ('active', 'trialing') AND s.organization_id = :oid"
)


def parse_period(
    start: str | None, end: str | None
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    end_dt = _parse_iso(end) if end else now
    start_dt = _parse_iso(start) if start else end_dt - timedelta(days=30)
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt >= end_dt:
        raise ValueError("period start must be before end")
    if (end_dt - start_dt).days > 366:
        raise ValueError("period cannot exceed 366 days")
    return start_dt, end_dt


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _period_payload(start: datetime, end: datetime) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat()}


def _infra_dollars(org_count: int, start: datetime, end: datetime) -> float:
    settings = get_settings()
    rate = settings.FINOPS_INFRA_COST_PER_ORG_MONTH_CENTS / 100.0
    days = max((end - start).total_seconds() / 86400.0, 1.0)
    return round(rate * org_count * (days / 30.0), 8)


def _margin(revenue_dollars: float, total_cost: float) -> tuple[float, float | None]:
    profit = round(revenue_dollars - total_cost, 8)
    if revenue_dollars <= 0:
        return profit, None
    return profit, round(profit / revenue_dollars * 100.0, 2)


async def usage_cost_breakdown(
    *,
    start: datetime,
    end: datetime,
    organization_id: UUID | None = None,
) -> dict[str, float]:
    """Sum classified LLM/embedding cost from usage_events in [start, end)."""
    session = await get_async_session()
    try:
        params: dict = {"start": start, "end": end}
        sql = _USAGE_SQL_ALL
        if organization_id is not None:
            sql = _USAGE_SQL_ORG
            params["oid"] = organization_id
        row = (await session.execute(sql, params)).fetchone()
        return {
            "llm": float(row.llm) if row else 0.0,
            "embedding": float(row.embedding) if row else 0.0,
            "requests": int(row.requests) if row else 0,
        }
    finally:
        await session.close()


async def _paid_revenue_cents(
    *,
    start: datetime,
    end: datetime,
    organization_id: UUID | None = None,
) -> int:
    session = await get_async_session()
    try:
        params: dict = {"start": start, "end": end}
        sql = _REVENUE_SQL_ALL
        if organization_id is not None:
            sql = _REVENUE_SQL_ORG
            params["oid"] = organization_id
        row = (await session.execute(sql, params)).fetchone()
        return int(row.revenue) if row else 0
    finally:
        await session.close()


async def _active_mrr_cents(organization_id: UUID | None = None) -> int:
    session = await get_async_session()
    try:
        if organization_id is not None:
            row = (
                await session.execute(_MRR_SQL_ORG, {"oid": organization_id})
            ).fetchone()
        else:
            row = (await session.execute(_MRR_SQL_ALL)).fetchone()
        return int(row.mrr_cents) if row else 0
    finally:
        await session.close()


async def _active_org_count(organization_id: UUID | None = None) -> int:
    if organization_id is not None:
        return 1
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT organization_id)::int AS n
                    FROM subscriptions
                    WHERE status IN ('active', 'trialing')
                    """
                )
            )
        ).fetchone()
        return int(row.n) if row else 0
    finally:
        await session.close()


async def _customer_stats(start: datetime, end: datetime) -> dict:
    session = await get_async_session()
    try:
        new_row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS n
                    FROM organizations
                    WHERE created_at >= :start AND created_at < :end
                    """
                ),
                {"start": start, "end": end},
            )
        ).fetchone()
        churned_row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS n
                    FROM subscriptions
                    WHERE status = 'canceled'
                      AND canceled_at IS NOT NULL
                      AND canceled_at >= :start AND canceled_at < :end
                    """
                ),
                {"start": start, "end": end},
            )
        ).fetchone()
        paid_orgs = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT organization_id)::int AS n
                    FROM invoices
                    WHERE status = 'paid'
                      AND paid_at IS NOT NULL
                      AND paid_at >= :start AND paid_at < :end
                    """
                ),
                {"start": start, "end": end},
            )
        ).fetchone()
        return {
            "new": int(new_row.n) if new_row else 0,
            "churned": int(churned_row.n) if churned_row else 0,
            "paying": int(paid_orgs.n) if paid_orgs else 0,
        }
    except Exception:
        await session.rollback()
        return {"new": 0, "churned": 0, "paying": 0}
    finally:
        await session.close()


async def _storage_rate_per_gb(organization_id: UUID | None) -> float:
    session = await get_async_session()
    try:
        if organization_id is not None:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(p.overage_storage_cost_per_gb, 0)::float AS rate
                        FROM subscriptions s
                        JOIN plans p ON p.id = s.plan_id
                        WHERE s.organization_id = :oid
                        ORDER BY s.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"oid": organization_id},
                )
            ).fetchone()
        else:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(AVG(p.overage_storage_cost_per_gb), 0)::float
                            AS rate
                        FROM subscriptions s
                        JOIN plans p ON p.id = s.plan_id
                        WHERE s.status IN ('active', 'trialing')
                        """
                    )
                )
            ).fetchone()
        return float(row.rate) if row else 0.0
    finally:
        await session.close()


async def _vector_points(organization_id: UUID | None) -> int:
    try:
        from qdrant_client import models as qdrant_models

        from src.infrastructure.qdrant.vector_store import (
            RAG_DOCUMENTS_COLLECTION,
            _get_client,
        )

        client = await _get_client()
        kwargs: dict = {
            "collection_name": RAG_DOCUMENTS_COLLECTION,
            "exact": True,
        }
        if organization_id is not None:
            kwargs["count_filter"] = qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="organization_id",
                        match=qdrant_models.MatchValue(value=str(organization_id)),
                    )
                ]
            )
        count = await client.count(**kwargs)
        return int(count.count or 0)
    except Exception:
        return 0


async def storage_dollars(organization_id: UUID | None) -> float:
    points = await _vector_points(organization_id)
    if points <= 0:
        return 0.0
    rate = await _storage_rate_per_gb(organization_id)
    if rate <= 0:
        return 0.0
    dim = max(get_settings().VECTOR_DIMENSION, 1)
    gb = points * dim * 4 / 1_000_000_000.0
    return round(gb * rate, 8)


def _economics(
    *,
    revenue_dollars: float,
    total_cost: float,
    profit: float,
    requests: int,
    customers: int,
) -> dict:
    def _ratio(num: float, den: int) -> float | None:
        if den <= 0:
            return None
        return round(num / den, 8)

    return {
        "cost_per_request": _ratio(total_cost, requests),
        "cost_per_customer": _ratio(total_cost, customers),
        "revenue_per_request": _ratio(revenue_dollars, requests),
        "margin_per_customer": _ratio(profit, customers),
        "requests": requests,
    }


async def _ensure_sources() -> None:
    from src.platform.billing.invoices import ensure_billing_tables
    from src.platform.usage.usage_engine import ensure_usage_table

    await ensure_usage_table()
    await ensure_billing_tables()


async def build_summary(start: datetime, end: datetime) -> dict:
    await _ensure_sources()
    usage = await usage_cost_breakdown(start=start, end=end)
    revenue_cents = await _paid_revenue_cents(start=start, end=end)
    mrr_cents = await _active_mrr_cents()
    active_orgs = await _active_org_count()
    storage = await storage_dollars(None)
    infra = _infra_dollars(active_orgs, start, end)
    costs = {
        "llm": round(usage["llm"], 8),
        "embedding": round(usage["embedding"], 8),
        "storage": storage,
        "infra": infra,
    }
    total_cost = sum(costs.values())
    revenue_dollars = revenue_cents / 100.0
    profit, margin = _margin(revenue_dollars, total_cost)
    stats = await _customer_stats(start, end)
    paying = stats["paying"]
    arpu = (revenue_cents // paying) if paying > 0 else None
    denom = paying if paying > 0 else active_orgs
    return {
        "period": _period_payload(start, end),
        "revenue_cents": revenue_cents,
        "revenue_basis": "invoices_paid",
        "mrr_cents": mrr_cents,
        "costs": costs,
        "gross_profit": profit,
        "gross_margin_pct": margin,
        "customers": {
            "new": stats["new"],
            "churned": stats["churned"],
            "arpu_cents": arpu,
        },
        "economics": _economics(
            revenue_dollars=revenue_dollars,
            total_cost=total_cost,
            profit=profit,
            requests=int(usage["requests"]),
            customers=denom,
        ),
    }


async def build_org_report(
    organization_id: UUID, start: datetime, end: datetime
) -> dict:
    await _ensure_sources()
    usage = await usage_cost_breakdown(
        start=start, end=end, organization_id=organization_id
    )
    revenue_cents = await _paid_revenue_cents(
        start=start, end=end, organization_id=organization_id
    )
    mrr_cents = await _active_mrr_cents(organization_id)
    storage = await storage_dollars(organization_id)
    infra = _infra_dollars(1, start, end)
    costs = {
        "llm": round(usage["llm"], 8),
        "embedding": round(usage["embedding"], 8),
        "storage": storage,
        "infra": infra,
    }
    total_cost = sum(costs.values())
    revenue_dollars = revenue_cents / 100.0
    profit, margin = _margin(revenue_dollars, total_cost)
    return {
        "organization_id": str(organization_id),
        "period": _period_payload(start, end),
        "revenue_cents": revenue_cents,
        "revenue_basis": "invoices_paid",
        "subscription_price_cents": mrr_cents,
        "mrr_cents": mrr_cents,
        "costs": costs,
        "gross_profit": profit,
        "gross_margin_pct": margin,
        "economics": _economics(
            revenue_dollars=revenue_dollars,
            total_cost=total_cost,
            profit=profit,
            requests=int(usage["requests"]),
            customers=1,
        ),
    }

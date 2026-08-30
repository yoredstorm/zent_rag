# =============================================================================
# Platform Control Center API — métricas y acciones cross-tenant
# =============================================================================
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import (
    PostgresAuditLogRepository,
    PostgresBillingRepository,
    PostgresOrganizationRepository,
    PostgresUserRepository,
    get_async_session,
)
from src.platform.audit.service import AuditLogService
from src.platform.rbac.policy import require_platform_admin

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/platform", tags=["Platform"])


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


_ORG_LIST_SQL = """
SELECT
    o.id,
    o.name,
    o.company_name,
    o.email,
    o.status,
    o.created_at,
    s.status AS subscription_status,
    s.payment_provider,
    s.current_period_end,
    p.name AS plan,
    COALESCE(p.is_trial, false) AS is_trial,
    COALESCE((
        SELECT SUM(i.total_cents)::bigint
        FROM invoices i
        WHERE i.organization_id = o.id
          AND i.status IN ('draft', 'open')
    ), 0) AS amount_due_cents
FROM organizations o
LEFT JOIN LATERAL (
    SELECT status, payment_provider, current_period_end, plan_id
    FROM subscriptions
    WHERE organization_id = o.id
    ORDER BY created_at DESC
    LIMIT 1
) s ON true
LEFT JOIN plans p ON p.id = s.plan_id
WHERE o.status <> 'deleted'
ORDER BY o.created_at DESC
"""

# Same list without invoices (fresh DBs / ensure_billing_tables failed).
_ORG_LIST_SQL_FALLBACK = """
SELECT
    o.id,
    o.name,
    o.company_name,
    o.email,
    o.status,
    o.created_at,
    s.status AS subscription_status,
    s.payment_provider,
    s.current_period_end,
    p.name AS plan,
    COALESCE(p.is_trial, false) AS is_trial,
    0::bigint AS amount_due_cents
FROM organizations o
LEFT JOIN LATERAL (
    SELECT status, payment_provider, current_period_end, plan_id
    FROM subscriptions
    WHERE organization_id = o.id
    ORDER BY created_at DESC
    LIMIT 1
) s ON true
LEFT JOIN plans p ON p.id = s.plan_id
WHERE o.status <> 'deleted'
ORDER BY o.created_at DESC
"""


def _org_list_item(row) -> dict:
    provider = row.payment_provider
    if provider is None and row.subscription_status is not None:
        provider = "manual"
    return {
        "id": str(row.id),
        "name": row.name,
        "company_name": row.company_name,
        "email": row.email,
        "status": row.status,
        "created_at": _iso(row.created_at),
        "subscription_status": row.subscription_status,
        "plan": row.plan,
        "is_trial": bool(row.is_trial),
        "payment_provider": provider,
        "amount_due_cents": int(row.amount_due_cents or 0),
        "next_renewal_at": _iso(row.current_period_end),
    }


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _client_ip(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


class ImpersonateBody(BaseModel):
    expires_seconds: int = Field(default=3600, ge=60, le=3600)


class PlanBody(BaseModel):
    plan_name: str = Field(..., min_length=1, max_length=100)


class EntitlementItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    value_type: Literal["bool", "int", "bigint"]
    value_bool: bool | None = None
    value_int: int | None = None


class PutEntitlementsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entitlements: list[EntitlementItem] = Field(..., min_length=1, max_length=50)


@router.get("/metrics", summary="Métricas globales del Control Center")
async def platform_metrics(request: Request):
    require_platform_admin(request)
    session = await get_async_session()
    try:
        mrr_row = (
            await session.execute(
                text(
                    """
                    SELECT COALESCE(SUM(
                        CASE
                            WHEN s.billing_interval = 'annual'
                                THEN (p.price_annual_cents / 12)
                            ELSE p.price_monthly_cents
                        END
                    ), 0)::int AS mrr_cents
                    FROM subscriptions s
                    JOIN plans p ON p.id = s.plan_id
                    WHERE s.status IN ('active', 'trialing')
                    """
                )
            )
        ).fetchone()
        mrr_cents = int(mrr_row.mrr_cents if mrr_row else 0)

        customers_row = (
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
        customers = int(customers_row.n if customers_row else 0)

        agents_row = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS n FROM agents WHERE is_active = true"
                )
            )
        ).fetchone()
        active_agents = int(agents_row.n if agents_row else 0)

        usage_row = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS requests,
                           COALESCE(SUM(estimated_cost), 0)::float AS cost
                    FROM usage_events
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    """
                )
            )
        ).fetchone()
        ai_requests_30d = int(usage_row.requests if usage_row else 0)
        llm_cost_30d = float(usage_row.cost if usage_row else 0.0)
    finally:
        await session.close()

    mrr_dollars = mrr_cents / 100.0
    if mrr_dollars <= 0 or llm_cost_30d <= 0:
        margin = None
    else:
        margin = round((mrr_dollars - llm_cost_30d) / mrr_dollars * 100.0, 2)

    return {
        "mrr_cents": mrr_cents,
        "arr_cents": mrr_cents * 12,
        "customers": customers,
        "active_agents": active_agents,
        "ai_requests_30d": ai_requests_30d,
        "llm_cost_30d": llm_cost_30d,
        "gross_margin_pct": margin,
    }


def _finops_period(start: str | None, end: str | None) -> tuple:
    from src.platform.finops.report import parse_period

    try:
        return parse_period(start, end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/finops/summary", summary="FinOps: revenue vs costes (plataforma)")
async def finops_summary(
    request: Request,
    start: str | None = None,
    end: str | None = None,
):
    require_platform_admin(request)
    from src.platform.finops.report import build_summary

    period_start, period_end = _finops_period(start, end)
    return await build_summary(period_start, period_end)


@router.get(
    "/finops/organizations/{org_id}",
    summary="FinOps: revenue vs costes de un customer",
)
async def finops_organization(
    org_id: str,
    request: Request,
    start: str | None = None,
    end: str | None = None,
):
    require_platform_admin(request)
    try:
        oid = UUID(org_id)
    except ValueError:
        raise HTTPException(404, "Organization not found")
    from src.infrastructure.postgres.relational_db import (
        PostgresOrganizationRepository,
    )
    from src.platform.finops.report import build_org_report

    org = await PostgresOrganizationRepository().get_by_id(oid)
    if org is None:
        raise HTTPException(404, "Organization not found")
    period_start, period_end = _finops_period(start, end)
    return await build_org_report(oid, period_start, period_end)


@router.get("/eval/summary", summary="Eval runs por org (sin texto de casos)")
async def platform_eval_summary(request: Request):
    """Counts only — never returns questions, answers, or retrieved chunks."""
    require_platform_admin(request)
    from src.rag.evaluation.store import ensure_eval_engine_tables

    await ensure_eval_engine_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT organization_id::text AS organization_id,
                           COUNT(*)::int AS run_count,
                           MAX(created_at) AS last_run_at
                    FROM eval_runs
                    GROUP BY organization_id
                    ORDER BY run_count DESC
                    LIMIT 200
                    """
                )
            )
        ).fetchall()
        total = (
            await session.execute(text("SELECT COUNT(*)::int AS n FROM eval_runs"))
        ).scalar() or 0
    finally:
        await session.close()
    return {
        "run_count": int(total),
        "organizations": [
            {
                "organization_id": r.organization_id,
                "run_count": int(r.run_count),
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            }
            for r in rows
        ],
    }


@router.get("/plans", summary="Planes y entitlements (Control Center)")
async def list_platform_plans(request: Request):
    require_platform_admin(request)
    from src.platform.billing.entitlements import get_entitlements_for_plans

    billing = PostgresBillingRepository()
    plans = await billing.get_plans(public_only=False)
    ents = await get_entitlements_for_plans([p.id for p in plans])
    return {
        "plans": [
            {
                "id": str(p.id),
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "is_trial": p.is_trial,
                "price_monthly_cents": p.price_monthly_cents,
                "entitlements": ents.get(p.id, {}),
            }
            for p in plans
        ]
    }


@router.put("/plans/{plan_id}/entitlements", summary="Actualizar entitlements de un plan")
async def put_plan_entitlements(plan_id: str, body: PutEntitlementsBody, request: Request):
    require_platform_admin(request)
    try:
        pid = UUID(plan_id)
    except ValueError:
        raise HTTPException(404, "Plan not found") from None
    from src.platform.billing.entitlements import upsert_plan_entitlements

    try:
        entitlements = await upsert_plan_entitlements(
            pid,
            [item.model_dump() for item in body.entitlements],
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "Plan not found":
            raise HTTPException(404, msg) from exc
        raise HTTPException(400, msg) from exc
    return {"plan_id": str(pid), "entitlements": entitlements}


@router.get("/organizations", summary="Listar organizaciones (Control Center)")
async def list_platform_organizations(request: Request):
    require_platform_admin(request)
    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()
    session = await get_async_session()
    try:
        try:
            rows = (await session.execute(text(_ORG_LIST_SQL))).fetchall()
        except Exception:
            await session.rollback()
            rows = (await session.execute(text(_ORG_LIST_SQL_FALLBACK))).fetchall()
    finally:
        await session.close()
    organizations = [_org_list_item(row) for row in rows]
    return {
        "organizations": organizations,
        "total": len(organizations),
    }


@router.get("/organizations/{org_id}", summary="Ficha de cliente")
async def get_platform_organization(org_id: str, request: Request):
    require_platform_admin(request)
    try:
        oid = UUID(org_id)
    except ValueError:
        raise HTTPException(404, "Organization not found")
    repo = PostgresOrganizationRepository()
    org = await repo.get_by_id(oid)
    if org is None:
        raise HTTPException(404, "Organization not found")
    billing = PostgresBillingRepository()
    sub = await billing.get_subscription_by_organization(oid)
    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()
    session = await get_async_session()
    try:
        users_n = (
            await session.execute(
                text("SELECT COUNT(*)::int AS n FROM users WHERE organization_id = :oid"),
                {"oid": oid},
            )
        ).scalar() or 0
        agents_n = (
            await session.execute(
                text(
                    "SELECT COUNT(*)::int AS n FROM agents "
                    "WHERE organization_id = :oid AND is_active = true"
                ),
                {"oid": oid},
            )
        ).scalar() or 0
        usage = (
            await session.execute(
                text(
                    """
                    SELECT COUNT(*)::int AS requests,
                           COALESCE(SUM(estimated_cost), 0)::float AS cost
                    FROM usage_events
                    WHERE organization_id = :oid
                      AND created_at >= NOW() - INTERVAL '30 days'
                    """
                ),
                {"oid": oid},
            )
        ).fetchone()
        try:
            due_row = (
                await session.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(total_cents), 0)::bigint AS amount_due_cents
                        FROM invoices
                        WHERE organization_id = :oid
                          AND status IN ('draft', 'open')
                        """
                    ),
                    {"oid": oid},
                )
            ).fetchone()
        except Exception:
            await session.rollback()
            due_row = None
        plan_row = None
        provider_row = None
        if sub is not None:
            plan_row = (
                await session.execute(
                    text(
                        "SELECT name, price_monthly_cents, price_annual_cents "
                        "FROM plans WHERE id = :pid"
                    ),
                    {"pid": sub.plan_id},
                )
            ).fetchone()
            provider_row = (
                await session.execute(
                    text(
                        "SELECT payment_provider FROM subscriptions WHERE id = :sid"
                    ),
                    {"sid": sub.id},
                )
            ).fetchone()
    finally:
        await session.close()

    mrr_cents = 0
    if sub is not None and plan_row is not None and str(sub.status) in ("active", "trialing"):
        if str(sub.billing_interval) == "annual":
            mrr_cents = int(plan_row.price_annual_cents // 12)
        else:
            mrr_cents = int(plan_row.price_monthly_cents)

    requests_30d = int(usage.requests) if usage else 0
    ai_cost_30d = float(usage.cost) if usage else 0.0
    mrr_dollars = mrr_cents / 100.0
    if mrr_dollars <= 0 or ai_cost_30d <= 0:
        margin = None
    else:
        margin = round((mrr_dollars - ai_cost_30d) / mrr_dollars * 100.0, 2)

    return {
        "id": str(org.id),
        "name": org.name,
        "company_name": org.company_name,
        "email": org.email,
        "status": org.status.value,
        "plan": plan_row.name if plan_row else None,
        "subscription_status": str(sub.status) if sub else None,
        "started": (sub.created_at.isoformat() if sub and sub.created_at else None),
        "mrr_cents": mrr_cents,
        "users": users_n,
        "agents": agents_n,
        "requests_30d": requests_30d,
        "ai_cost_30d": ai_cost_30d,
        "margin": margin,
        "payment_provider": (
            str(provider_row.payment_provider)
            if provider_row and provider_row.payment_provider
            else ("manual" if sub else None)
        ),
        "amount_due_cents": int(due_row.amount_due_cents) if due_row else 0,
        "next_renewal_at": _iso(sub.current_period_end) if sub else None,
    }


@router.post("/organizations/{org_id}/plan")
async def change_plan(org_id: str, body: PlanBody, request: Request):
    ctx = require_platform_admin(request)
    oid = _parse_org(org_id)
    billing_repo = PostgresBillingRepository()
    sub = await billing_repo.get_subscription_by_organization(oid)
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository
    from src.platform.billing.service import BillingService

    svc = BillingService(billing_repo, PostgresApiKeyRepository())
    try:
        result = await svc.upgrade_plan(sub.id, body.plan_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await _audit().write_or_raise(
        ctx,
        "platform.plan_change",
        "organization",
        oid,
        organization_id=oid,
        ip_address=_client_ip(request),
        metadata={"plan_name": body.plan_name, "actor_user_id": str(ctx.user_id)},
    )
    return result


@router.post("/organizations/{org_id}/pause")
async def pause_org(org_id: str, request: Request):
    return await _transition(org_id, request, "paused", "platform.pause")


@router.post("/organizations/{org_id}/suspend")
async def suspend_org(org_id: str, request: Request):
    return await _transition(org_id, request, "suspended", "platform.suspend")


@router.post("/organizations/{org_id}/cancel")
async def cancel_org(org_id: str, request: Request):
    ctx = require_platform_admin(request)
    oid = _parse_org(org_id)
    billing_repo = PostgresBillingRepository()
    sub = await billing_repo.get_subscription_by_organization(oid)
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository
    from src.platform.billing.service import BillingService

    svc = BillingService(billing_repo, PostgresApiKeyRepository())
    ok = await svc.transition_status(sub.id, "canceled")
    if not ok:
        await svc.cancel_subscription(sub.id)
    else:
        await _subscription_event(sub, "canceled", ctx.user_id)
    await _audit().write_or_raise(
        ctx,
        "platform.cancel",
        "organization",
        oid,
        organization_id=oid,
        ip_address=_client_ip(request),
        metadata={"actor_user_id": str(ctx.user_id)},
    )
    return {"status": "canceled", "organization_id": str(oid)}


@router.post("/organizations/{org_id}/usage/reset")
async def reset_usage(org_id: str, request: Request):
    ctx = require_platform_admin(request)
    oid = _parse_org(org_id)
    billing_repo = PostgresBillingRepository()
    sub = await billing_repo.get_subscription_by_organization(oid)
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE request_quota SET request_count = 0, reset_at = NOW() "
                "WHERE subscription_id = :sid "
                "AND quota_year = EXTRACT(YEAR FROM NOW())::int "
                "AND quota_month = EXTRACT(MONTH FROM NOW())::int"
            ),
            {"sid": sub.id},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
    await _subscription_event(sub, "usage_reset", ctx.user_id)
    await _audit().write_or_raise(
        ctx,
        "platform.usage_reset",
        "organization",
        oid,
        organization_id=oid,
        ip_address=_client_ip(request),
        metadata={"actor_user_id": str(ctx.user_id)},
    )
    return {"status": "reset", "organization_id": str(oid)}


@router.post("/organizations/{org_id}/impersonate")
async def impersonate(org_id: str, body: ImpersonateBody, request: Request):
    ctx = require_platform_admin(request)
    oid = _parse_org(org_id)
    org = await PostgresOrganizationRepository().get_by_id(oid)
    if org is None:
        raise HTTPException(404, "Organization not found")
    user = await PostgresUserRepository().get_by_external_id(oid, "default-admin")
    if user is None:
        user = await PostgresUserRepository().get_any_user(oid)
    if user is None:
        raise HTTPException(404, "No user to impersonate in this organization")

    await _audit().write_or_raise(
        ctx,
        "platform.impersonate",
        "organization",
        oid,
        organization_id=oid,
        ip_address=_client_ip(request),
        metadata={
            "actor_user_id": str(ctx.user_id),
            "target_organization_id": str(oid),
            "target_user_id": str(user.id),
            "expires_seconds": body.expires_seconds,
        },
    )

    from src.platform.auth.session import encrypt_session

    ttl_hours = body.expires_seconds / 3600.0
    token = encrypt_session(user.id, oid, ttl_hours=ttl_hours)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_seconds": body.expires_seconds,
        "organization_id": str(oid),
    }


@router.get("/notifications", summary="Inbox del Control Center")
async def list_platform_notifications(request: Request):
    require_platform_admin(request)
    from src.platform.notifications import list_notifications

    items, unread = await list_notifications(limit=50)
    return {"notifications": items, "unread_count": unread}


@router.post("/notifications/{notification_id}/read")
async def read_platform_notification(notification_id: str, request: Request):
    require_platform_admin(request)
    try:
        nid = UUID(notification_id)
    except ValueError:
        raise HTTPException(404, "Notification not found") from None
    from src.platform.notifications import mark_notification_read

    await mark_notification_read(nid)
    return {"status": "read", "id": str(nid)}


def _parse_org(org_id: str) -> UUID:
    try:
        return UUID(org_id)
    except ValueError:
        raise HTTPException(404, "Organization not found") from None


async def _subscription_event(sub, event_type: str, actor_user_id) -> None:
    from src.platform.billing.entitlements import record_subscription_event

    await record_subscription_event(
        subscription_id=sub.id,
        organization_id=sub.organization_id,
        event_type=event_type,
        from_plan_id=sub.plan_id,
        actor_user_id=actor_user_id,
    )


async def _transition(org_id: str, request: Request, new_status: str, action: str) -> dict:
    ctx = require_platform_admin(request)
    oid = _parse_org(org_id)
    billing_repo = PostgresBillingRepository()
    sub = await billing_repo.get_subscription_by_organization(oid)
    if sub is None:
        raise HTTPException(404, "Subscription not found")
    from src.infrastructure.postgres.relational_db import PostgresApiKeyRepository
    from src.platform.billing.service import BillingService

    svc = BillingService(billing_repo, PostgresApiKeyRepository())
    ok = await svc.transition_status(sub.id, new_status)
    if not ok:
        raise HTTPException(
            409,
            f"Cannot transition subscription from {sub.status} to {new_status}",
        )
    event_type = {"paused": "paused", "suspended": "suspended"}.get(new_status)
    if event_type:
        await _subscription_event(sub, event_type, ctx.user_id)
    await _audit().write_or_raise(
        ctx,
        action,
        "organization",
        oid,
        organization_id=oid,
        ip_address=_client_ip(request),
        metadata={"actor_user_id": str(ctx.user_id), "status": new_status},
    )
    return {"status": new_status, "organization_id": str(oid)}

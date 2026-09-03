# =============================================================================
# Platform Control Center API — métricas y acciones cross-tenant
# =============================================================================
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
from src.platform.rbac.authorization import require_platform_permission

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
    ctx = require_platform_permission(request, "analytics.read")
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
    ctx = require_platform_permission(request, "analytics.read")
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
    ctx = require_platform_permission(request, "analytics.read")
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
    ctx = require_platform_permission(request, "analytics.read")
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
    ctx = require_platform_permission(request, "billing.read")
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
    ctx = require_platform_permission(request, "billing.manage")
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
    ctx = require_platform_permission(request, "tenant.read")
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
    ctx = require_platform_permission(request, "tenant.read")
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
    ctx = require_platform_permission(request, "billing.manage")
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
    ctx = require_platform_permission(request, "tenant.suspend")
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
    ctx = require_platform_permission(request, "billing.manage")
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
    ctx = require_platform_permission(request, "support.impersonate")
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
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.notifications import list_notifications

    items, unread = await list_notifications(limit=50)
    return {"notifications": items, "unread_count": unread}


@router.post("/notifications/{notification_id}/read")
async def read_platform_notification(notification_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
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
    ctx = require_platform_permission(request, "tenant.suspend")
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

# ---------------------------------------------------------------------------
# Platform RBAC — roles y usuarios de plataforma
# ---------------------------------------------------------------------------


@router.get("/roles", summary="Roles de plataforma con permisos")
async def list_platform_roles(request: Request):
    ctx = require_platform_permission(request, "platform.users.manage")
    from src.platform.rbac.repo import list_platform_roles as _list_roles

    roles = await _list_roles()
    return {"roles": roles, "count": len(roles)}


@router.get("/users", summary="Usuarios de plataforma con roles")
async def list_platform_users(request: Request):
    ctx = require_platform_permission(request, "platform.users.manage")
    from src.platform.rbac.repo import list_platform_users as _list_users

    users = await _list_users()
    return {"users": users, "count": len(users)}


class PlatformRoleAssignment(BaseModel):
    role_name: str = Field(..., min_length=2, max_length=100)
    action: Literal["assign", "revoke"] = "assign"


@router.post("/users/{user_id}/roles", summary="Asignar/revocar rol de plataforma")
async def assign_platform_user_role(
    user_id: str, body: PlatformRoleAssignment, request: Request
):

    ctx = require_platform_permission(request, "platform.users.manage")
    from src.platform.rbac.repo import (
        assign_platform_role,
        revoke_platform_role,
    )

    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(400, "user_id must be a valid UUID")
    if body.action == "assign":
        changed = await assign_platform_role(uid, body.role_name)
    else:
        changed = await revoke_platform_role(uid, body.role_name)
    if not changed:
        raise HTTPException(404, "Role or user not found")
    await _audit().write_or_raise(
        ctx,
        "platform.role_assigned" if body.action == "assign" else "platform.role_revoked",
        "platform_user",
        uid,
        ip_address=_client_ip(request),
        metadata={"role_name": body.role_name, "action": body.action},
    )
    return {"user_id": str(uid), "role_name": body.role_name, "action": body.action}


# ---------------------------------------------------------------------------
# Subscriptions — visión global
# ---------------------------------------------------------------------------


@router.get("/subscriptions", summary="Suscripciones de todos los tenants")
async def list_platform_subscriptions(request: Request):
    ctx = require_platform_permission(request, "billing.read")
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT s.id, s.organization_id, o.name AS org_name, "
                    "p.name AS plan_name, s.status, s.billing_interval, "
                    "s.current_period_start, s.current_period_end, "
                    "s.trial_end AS trial_ends_at, s.auto_renew, s.payment_provider "
                    "FROM subscriptions s "
                    "JOIN organizations o ON o.id = s.organization_id "
                    "JOIN plans p ON p.id = s.plan_id "
                    "ORDER BY s.created_at DESC LIMIT 500"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "subscriptions": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "organization_name": r.org_name,
                "plan": r.plan_name,
                "status": r.status,
                "interval": r.billing_interval,
                "period_start": _iso(r.current_period_start),
                "period_end": _iso(r.current_period_end),
                "trial_ends_at": _iso(r.trial_ends_at),
                "auto_renew": bool(r.auto_renew),
                "provider": r.payment_provider,
            }
            for r in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# Audit — viewer global
# ---------------------------------------------------------------------------


@router.get("/audit", summary="Audit logs globales (filtrables por tenant/acción)")
async def list_platform_audit(
    request: Request,
    tenant_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    ctx = require_platform_permission(request, "audit.read")
    from src.infrastructure.postgres.relational_db import (
        PostgresAuditLogRepository,
    )

    oid = UUID(tenant_id) if tenant_id else None
    entries = await PostgresAuditLogRepository().list_all_entries(
        limit=min(limit, 500),
        offset=offset,
        organization_id=oid,
        action=action,
    )
    return {
        "entries": [
            {
                "organization_id": str(e.organization_id) if e.organization_id else None,
                "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "created_at": _iso(e.created_at),
                "metadata": e.metadata or {},
            }
            for e in entries
        ],
        "count": len(entries),
    }


# ---------------------------------------------------------------------------
# Operations — jobs de ingestión globales
# ---------------------------------------------------------------------------


@router.get("/operations", summary="Operaciones globales (jobs, errores)")
async def list_platform_operations(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    session = await get_async_session()
    try:
        jobs = (
            await session.execute(
                text(
                    "SELECT j.id, j.organization_id, o.name AS org_name, "
                    "j.job_type, j.status, j.progress, j.attempts, "
                    "j.error_summary, j.created_at, j.updated_at "
                    "FROM ingestion_jobs j "
                    "JOIN organizations o ON o.id = j.organization_id "
                    "ORDER BY j.created_at DESC LIMIT 200"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "jobs": [
            {
                "id": str(r.id),
                "organization_id": str(r.organization_id),
                "organization_name": r.org_name,
                "job_type": r.job_type,
                "status": r.status,
                "progress": r.progress,
                "attempts": r.attempts,
                "error_summary": r.error_summary,
                "created_at": _iso(r.created_at),
                "updated_at": _iso(r.updated_at),
            }
            for r in jobs
        ],
        "count": len(jobs),
    }


# ---------------------------------------------------------------------------
# Settings — estado de configuración de plataforma (sin secrets)
# ---------------------------------------------------------------------------


@router.get("/settings", summary="Configuración de plataforma (sin secrets)")
async def get_platform_settings(request: Request):
    ctx = require_platform_permission(request, "platform.settings.manage")
    from src.core.config import get_settings

    s = get_settings()
    return {
        "environment": s.ENVIRONMENT,
        "sql_expert_enabled": s.RAG_SQL_EXPERT_ENABLED,
        "mcp_enabled": s.RAG_MCP_ENABLED,
        "lazy_ingestion_enabled": s.RAG_LAZY_INGESTION_ENABLED,
        "admin_enabled": s.RAG_ADMIN_ENABLED,
        "seed_demo_data": s.SEED_DEMO_DATA,
        "embedding_model": s.EMBEDDING_MODEL,
        "default_model": s.LITELLM_DEFAULT_MODEL,
        "portal_session_ttl_hours": s.PORTAL_SESSION_TTL_HOURS,
        "rate_limit_per_minute": s.RATE_LIMIT_PER_MINUTE,
    }


# ---------------------------------------------------------------------------
# Tenant 360 — sub-recursos por organización
# ---------------------------------------------------------------------------


async def _require_org(request: Request, org_id: str, permission: str) -> UUID:
    ctx = require_platform_permission(request, permission)
    oid = _parse_org(org_id)
    org = await PostgresOrganizationRepository().get_by_id(oid)
    if org is None:
        raise HTTPException(404, "Organization not found")
    return oid


@router.get("/organizations/{org_id}/users", summary="Tenant 360: usuarios")
async def tenant_users(org_id: str, request: Request):
    oid = await _require_org(request, org_id, "tenant.read")
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT u.id, u.email, u.last_active_at, "
                    "COALESCE(array_agg(r.name ORDER BY r.name) FILTER (WHERE r.name IS NOT NULL), '{}') AS roles "
                    "FROM memberships m "
                    "JOIN users u ON u.id = m.user_id "
                    "JOIN roles r ON r.id = m.role_id "
                    "WHERE m.organization_id = :oid "
                    "GROUP BY u.id, u.email, u.last_active_at ORDER BY u.email"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "users": [
            {
                "id": str(r.id),
                "email": r.email,
                "roles": list(r.roles),
                "last_active_at": _iso(r.last_active_at),
            }
            for r in rows
        ]
    }


@router.get("/organizations/{org_id}/agents", summary="Tenant 360: agentes")
async def tenant_agents(org_id: str, request: Request):
    oid = await _require_org(request, org_id, "tenant.read")
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT a.id, a.name, a.model, a.is_active, a.created_at, "
                    "COUNT(d.id) AS deployments "
                    "FROM agents a "
                    "LEFT JOIN deployments d ON d.agent_id = a.id AND d.status = 'healthy' "
                    "WHERE a.organization_id = :oid "
                    "GROUP BY a.id, a.name, a.model, a.is_active, a.created_at "
                    "ORDER BY a.created_at DESC"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "agents": [
            {
                "id": str(r.id),
                "name": r.name,
                "model": r.model,
                "is_active": bool(r.is_active),
                "deployments": int(r.deployments),
                "created_at": _iso(r.created_at),
            }
            for r in rows
        ]
    }


@router.get("/organizations/{org_id}/sources", summary="Tenant 360: fuentes de datos")
async def tenant_sources(org_id: str, request: Request):
    oid = await _require_org(request, org_id, "tenant.read")
    session = await get_async_session()
    try:
        sources = (
            await session.execute(
                text(
                    "SELECT s.id, s.name, s.type, s.status, s.created_at, "
                    "COALESCE(ss.last_success_at, NULL) AS last_success_at "
                    "FROM kb_sources s "
                    "LEFT JOIN source_sync_state ss ON ss.source_id = s.id "
                    "WHERE s.organization_id = :oid ORDER BY s.created_at DESC"
                ),
                {"oid": oid},
            )
        ).fetchall()
        kbs = (
            await session.execute(
                text(
                    "SELECT id, name, chunking_strategy, retrieval_strategy, created_at "
                    "FROM knowledge_bases WHERE organization_id = :oid "
                    "ORDER BY created_at DESC"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "sources": [
            {
                "id": str(r.id),
                "name": r.name,
                "type": r.type,
                "status": r.status,
                "last_success_at": _iso(r.last_success_at),
                "created_at": _iso(r.created_at),
            }
            for r in sources
        ],
        "knowledge_bases": [
            {
                "id": str(r.id),
                "name": r.name,
                "chunking_strategy": r.chunking_strategy,
                "retrieval_strategy": r.retrieval_strategy,
                "created_at": _iso(r.created_at),
            }
            for r in kbs
        ],
    }


@router.get("/organizations/{org_id}/billing", summary="Tenant 360: billing")
async def tenant_billing(org_id: str, request: Request):
    oid = await _require_org(request, org_id, "billing.read")
    session = await get_async_session()
    try:
        sub = (
            await session.execute(
                text(
                    "SELECT s.id, p.name AS plan, s.status, s.billing_interval, "
                    "s.current_period_start, s.current_period_end, s.auto_renew "
                    "FROM subscriptions s JOIN plans p ON p.id = s.plan_id "
                    "WHERE s.organization_id = :oid ORDER BY s.created_at DESC LIMIT 1"
                ),
                {"oid": oid},
            )
        ).fetchone()
        invoices = (
            await session.execute(
                text(
                    "SELECT id, status, total_cents, paid_at, created_at "
                    "FROM invoices WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 25"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "subscription": (
            {
                "id": str(sub.id),
                "plan": sub.plan,
                "status": sub.status,
                "interval": sub.billing_interval,
                "period_start": _iso(sub.current_period_start),
                "period_end": _iso(sub.current_period_end),
                "auto_renew": bool(sub.auto_renew),
            }
            if sub
            else None
        ),
        "invoices": [
            {
                "id": str(r.id),
                "status": r.status,
                "total_cents": int(r.total_cents or 0),
                "paid_at": _iso(r.paid_at),
                "created_at": _iso(r.created_at),
            }
            for r in invoices
        ],
    }


@router.get("/organizations/{org_id}/security", summary="Tenant 360: security")
async def tenant_security(org_id: str, request: Request):
    oid = await _require_org(request, org_id, "tenant.read")
    session = await get_async_session()
    try:
        keys = (
            await session.execute(
                text(
                    "SELECT id, name, key_prefix, scopes, is_active, "
                    "last_used_at, expires_at, created_at "
                    "FROM api_keys WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"oid": oid},
            )
        ).fetchall()
    finally:
        await session.close()
    return {
        "api_keys": [
            {
                "id": str(r.id),
                "name": r.name,
                "prefix": r.key_prefix,
                "scopes": list(r.scopes or []),
                "is_active": bool(r.is_active),
                "last_used_at": _iso(r.last_used_at),
                "expires_at": _iso(r.expires_at),
                "created_at": _iso(r.created_at),
            }
            for r in keys
        ]
    }


@router.get("/organizations/{org_id}/audit", summary="Tenant 360: audit")
async def tenant_audit(
    org_id: str, request: Request, limit: int = 100, offset: int = 0
):
    oid = await _require_org(request, org_id, "audit.read")
    from src.infrastructure.postgres.relational_db import (
        PostgresAuditLogRepository,
    )

    entries = await PostgresAuditLogRepository().list_all_entries(
        limit=min(limit, 500), offset=offset, organization_id=oid
    )
    return {
        "entries": [
            {
                "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
                "action": e.action,
                "resource_type": e.resource_type,
                "resource_id": e.resource_id,
                "created_at": _iso(e.created_at),
                "metadata": e.metadata or {},
            }
            for e in entries
        ],
        "count": len(entries),
    }


@router.get("/tenants/{org_id}/health", summary="Health score del tenant")
async def tenant_health(org_id: str, request: Request):
    ctx = require_platform_permission(request, "tenant.read")
    oid = _parse_org(org_id)
    org = await PostgresOrganizationRepository().get_by_id(oid)
    if org is None:
        raise HTTPException(404, "Organization not found")

    session = await get_async_session()
    try:
        usage = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS requests, COALESCE(SUM(total_tokens), 0) AS tokens, "
                    "COALESCE(SUM(estimated_cost), 0) AS cost "
                    "FROM usage_events WHERE organization_id = :oid "
                    "AND created_at > NOW() - INTERVAL '30 days'"
                ),
                {"oid": oid},
            )
        ).fetchone()
        errors = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM usage_events "
                    "WHERE organization_id = :oid AND status = 'failed' "
                    "AND created_at > NOW() - INTERVAL '7 days'"
                ),
                {"oid": oid},
            )
        ).scalar()
        sub = (
            await session.execute(
                text(
                    "SELECT status FROM subscriptions WHERE organization_id = :oid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"oid": oid},
            )
        ).fetchone()
    finally:
        await session.close()

    sub_status = sub.status if sub else None
    score = 100
    if org.status == "suspended":
        score -= 60
    if sub_status in ("canceled", "expired", "paused"):
        score -= 30
    if sub_status == "past_due":
        score -= 20
    if int(usage.requests or 0) == 0:
        score -= 15
    if int(errors or 0) > 10:
        score -= 10
    score = max(0, min(100, score))
    label = "HEALTHY" if score >= 70 else "WATCH" if score >= 40 else "AT_RISK"
    return {
        "organization_id": str(oid),
        "score": score,
        "label": label,
        "requests_30d": int(usage.requests or 0),
        "tokens_30d": int(usage.tokens or 0),
        "cost_30d": float(usage.cost or 0),
        "errors_7d": int(errors or 0),
        "subscription_status": sub_status,
        "organization_status": org.status.value,
    }

@router.get("/finops/breakdown", summary="Costos por workspace/agent/deployment/provider/model")
async def platform_finops_breakdown(
    request: Request,
    organization_id: str | None = None,
    days: int = 30,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.finops.breakdown import usage_breakdown

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (await session.execute(
                text("SELECT id FROM organizations WHERE status <> 'deleted'")
            )).fetchall()
        finally:
            await session.close()
        return {"organizations": [await usage_breakdown(r.id, days) for r in rows]}
    return await usage_breakdown(oid, days)


@router.get("/finops/economics", summary="Cost/request y cost/1K requests (org)")
async def platform_finops_economics(
    request: Request,
    organization_id: str | None = None,
    days: int = 30,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.finops.breakdown import economics

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (await session.execute(
                text("SELECT id FROM organizations WHERE status <> 'deleted'")
            )).fetchall()
        finally:
            await session.close()
        return {"organizations": [await economics(r.id, days) for r in rows]}
    return await economics(oid, days)


@router.post("/finops/check", summary="Ejecutar checks FinOps (alerts)")
async def platform_finops_check(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "billing.manage")
    from src.platform.finops.alerts import check_organization

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (await session.execute(
                text("SELECT id FROM organizations WHERE status <> 'deleted'")
            )).fetchall()
        finally:
            await session.close()
        total = []
        for r in rows:
            total.extend(await check_organization(r.id))
        return {"alerts_created": total, "count": len(total)}
    return {"alerts_created": await check_organization(oid), "count": 0}


@router.get("/finops/alerts", summary="Alertas FinOps de un tenant")
async def platform_finops_alerts(request: Request, organization_id: str):
    ctx = require_platform_permission(request, "billing.read")
    from src.platform.finops.alerts import list_alerts

    oid = _parse_org(organization_id)
    alerts = await list_alerts(oid)
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/finops/alerts/{alert_id}/ack", summary="Reconocer alerta FinOps")
async def platform_finops_ack(request: Request, alert_id: str, organization_id: str):
    ctx = require_platform_permission(request, "billing.read")
    from src.platform.finops.alerts import acknowledge_alert

    oid = _parse_org(organization_id)
    ok = await acknowledge_alert(oid, UUID(alert_id))
    if not ok:
        raise HTTPException(404, "Alert not found")
    return {"status": "acknowledged"}


@router.put("/finops/organizations/{org_id}/budget", summary="Fijar budget FinOps del tenant")
async def platform_finops_budget(org_id: str, body: FinOpsBudgetIn, request: Request):
    ctx = require_platform_permission(request, "billing.manage")
    oid = _parse_org(org_id)
    session = await get_async_session()
    try:
        await session.execute(
            text(
                "UPDATE organizations SET finops_budget_cents = :cents "
                "WHERE id = :oid"
            ),
            {"cents": body.budget_cents, "oid": oid},
        )
        await session.commit()
    finally:
        await session.close()
    return {"organization_id": str(oid), "budget_cents": body.budget_cents}


class FinOpsBudgetIn(BaseModel):
    budget_cents: int = Field(..., ge=0)

# ------------------------------------------------------------------ PROMPT 08
# Observability & incident management

@router.get("/health", summary="Estado de salud del sistema")
async def platform_system_health(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.observability.health import system_health

    return await system_health()


@router.get("/deployments/{deployment_id}/slos", summary="SLIs/SLOs de un deployment")
async def platform_deployment_slos(deployment_id: str, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.observability.slos import deployment_slos

    did = UUID(deployment_id)
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id FROM deployments WHERE id = :did"),
                {"did": did},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "Deployment not found")
    slos = await deployment_slos(row.organization_id, did)
    if slos is None:
        raise HTTPException(404, "Deployment not found")
    return slos


@router.get("/organizations/{org_id}/slos", summary="SLOs por deployment de un tenant")
async def platform_org_slos(org_id: str, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.observability.slos import org_slos

    oid = _parse_org(org_id)
    return await org_slos(oid)


@router.post("/obs/check", summary="Ejecutar checks de observabilidad (alerts)")
async def platform_obs_check(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.observability.alerts import check_organization

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE status <> 'deleted'")
                )
            ).fetchall()
        finally:
            await session.close()
        total = []
        for r in rows:
            total.extend(await check_organization(r.id))
        return {"alerts_created": total, "count": len(total)}
    return {"alerts_created": await check_organization(oid), "count": 0}


@router.get("/obs/alerts", summary="Alertas de incidentes")
async def platform_obs_alerts(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.observability.alerts import list_alerts

    oid = UUID(organization_id) if organization_id else None
    alerts = await list_alerts(oid, status=status, limit=min(limit, 200))
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/obs/alerts/{alert_id}/resolve", summary="Resolver alerta de incidente")
async def platform_obs_resolve(alert_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.observability.alerts import resolve_alert

    ok = await resolve_alert(UUID(alert_id))
    if not ok:
        raise HTTPException(404, "Alert not found or already resolved")
    return {"status": "resolved"}


@router.post("/obs/alerts/{alert_id}/ack", summary="Reconocer alerta de incidente")
async def platform_obs_ack(alert_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.observability.alerts import acknowledge_alert

    ok = await acknowledge_alert(UUID(alert_id))
    if not ok:
        raise HTTPException(404, "Alert not found or not open")
    return {"status": "acknowledged"}


@router.put("/organizations/{org_id}/ops-webhook", summary="Configurar webhook de alertas")
async def platform_ops_webhook(org_id: str, body: OpsWebhookIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.observability.alerts import set_webhook

    oid = _parse_org(org_id)
    await set_webhook(oid, body.url, body.enabled)
    return {"organization_id": str(oid), "url": body.url, "enabled": body.enabled}


class OpsWebhookIn(BaseModel):
    url: str | None = None
    enabled: bool = True

# ------------------------------------------------------------------ PROMPT 10
# Disaster Recovery

@router.get("/dr/regions", summary="Catálogo de regiones DR")
async def platform_dr_regions(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT code, name, active FROM dr_regions ORDER BY code")
            )
        ).fetchall()
    finally:
        await session.close()
    return {"regions": [{"code": r.code, "name": r.name, "active": bool(r.active)} for r in rows]}


@router.get("/dr/organizations/{org_id}", summary="Perfil DR del tenant")
async def platform_dr_profile(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.dr.disaster_recovery import get_org_dr_profile

    oid = _parse_org(org_id)
    return await get_org_dr_profile(oid)


@router.put("/dr/organizations/{org_id}", summary="Actualizar perfil DR del tenant")
async def platform_dr_profile_put(org_id: str, body: DrProfileIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.dr.disaster_recovery import set_org_dr_profile

    oid = _parse_org(org_id)
    await set_org_dr_profile(
        oid,
        regions=body.regions,
        rpo_minutes=body.rpo_minutes,
        backup_enabled=body.backup_enabled,
    )
    return {"status": "saved", "organization_id": str(oid)}


@router.post("/dr/organizations/{org_id}/backup", summary="Ejecutar backup manual")
async def platform_dr_backup(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.dr.disaster_recovery import create_backup

    oid = _parse_org(org_id)
    return await create_backup(oid, trigger="manual")


@router.get("/dr/backups", summary="Listar backups DR")
async def platform_dr_backups(
    request: Request,
    organization_id: str | None = None,
    limit: int = 50,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.dr.disaster_recovery import list_backups

    oid = UUID(organization_id) if organization_id else None
    backups = await list_backups(oid, limit=min(limit, 200))
    return {"backups": backups, "count": len(backups)}


@router.post("/dr/backups/{backup_id}/drill", summary="DR drill: restaurar a standby DB")
async def platform_dr_drill(backup_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.dr.disaster_recovery import dr_drill

    return await dr_drill(UUID(backup_id))


@router.post("/dr/prune", summary="Purgar backups viejos (retención en días)")
async def platform_dr_prune(body: DrPruneIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.dr.disaster_recovery import prune_backups

    oid = UUID(body.organization_id) if body.organization_id else None
    removed = await prune_backups(oid, retention=body.retention_days)
    return {"removed": removed}


@router.get("/dr/readiness", summary="Readiness DR por organización")
async def platform_dr_readiness(
    request: Request,
    organization_id: str | None = None,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.dr.disaster_recovery import dr_readiness

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE status <> 'deleted'")
                )
            ).fetchall()
        finally:
            await session.close()
        return {"organizations": [await dr_readiness(r.id) for r in rows]}
    return await dr_readiness(oid)


class DrProfileIn(BaseModel):
    regions: list[str] | None = None
    rpo_minutes: int | None = Field(default=None, ge=5, le=43200)
    backup_enabled: bool | None = None


class DrPruneIn(BaseModel):
    organization_id: str | None = None
    retention_days: int = Field(..., ge=1, le=3650)

# ------------------------------------------------------------------ PROMPT 11
# Governance & Data Residency

@router.get("/governance/regions", summary="Regiones para residencia de datos")
async def platform_gov_regions(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text("SELECT code, name, active FROM dr_regions ORDER BY code")
            )
        ).fetchall()
    finally:
        await session.close()
    return {"regions": [{"code": r.code, "name": r.name, "active": bool(r.active)} for r in rows]}


@router.get("/governance/organizations/{org_id}", summary="Perfil governance del tenant")
async def platform_gov_profile(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.governance.governance import get_org_governance

    oid = _parse_org(org_id)
    return await get_org_governance(oid)


@router.put("/governance/organizations/{org_id}", summary="Actualizar retención/residencia/DSR")
async def platform_gov_profile_put(org_id: str, body: GovProfileIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import set_org_governance

    oid = _parse_org(org_id)
    await set_org_governance(
        oid,
        retention_days=body.retention_days,
        data_residency_region=body.data_residency_region,
        dsr_contact_email=body.dsr_contact_email,
    )
    return {"status": "saved", "organization_id": str(oid)}


@router.post("/governance/purge", summary="Aplicar retención (dry-run o ejecutar)")
async def platform_gov_purge(body: GovPurgeIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import enforce_retention

    oid = UUID(body.organization_id) if body.organization_id else None
    return await enforce_retention(dry_run=body.dry_run, organization_id=oid)


@router.post("/governance/organizations/{org_id}/dsr-export", summary="Exportar datos personales (DSR)")
async def platform_gov_dsr_export(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import dsr_export

    oid = _parse_org(org_id)
    return await dsr_export(oid)


@router.post("/governance/organizations/{org_id}/dsr-erasure", summary="Borrar datos personales (DSR)")
async def platform_gov_dsr_erasure(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import dsr_erasure

    oid = _parse_org(org_id)
    return await dsr_erasure(oid)


@router.get("/governance/compliance-events", summary="Eventos de cumplimiento")
async def platform_gov_events(
    request: Request,
    organization_id: str | None = None,
    limit: int = 50,
):
    ctx = require_platform_permission(request, "audit.read")
    from src.platform.governance.governance import list_compliance_events

    oid = UUID(organization_id) if organization_id else None
    events = await list_compliance_events(oid, limit=min(limit, 200))
    return {"events": events, "count": len(events)}


# KMS

@router.get("/governance/kms/status", summary="Estado del KMS")
async def platform_kms_status(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.governance.governance import kms_status

    return await kms_status()


@router.get("/governance/kms/keys", summary="Claves KMS")
async def platform_kms_keys(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.governance.governance import list_kms_keys

    keys = await list_kms_keys()
    return {"keys": keys, "count": len(keys)}


@router.post("/governance/kms/keys", status_code=201, summary="Crear clave KMS")
async def platform_kms_create(request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import create_kms_key

    return await create_kms_key()


@router.post("/governance/kms/keys/{key_id}/rotate", summary="Rotar clave KMS")
async def platform_kms_rotate(key_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.governance.governance import rotate_kms_key

    return await rotate_kms_key()


@router.post("/governance/kms/roundtrip", summary="Verificar envelope encrypt/decrypt")
async def platform_kms_roundtrip(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.governance.governance import envelope_decrypt, envelope_encrypt

    payload = b"governance-kms-roundtrip-probe"
    enc = await envelope_encrypt(payload)
    dec = await envelope_decrypt(enc["key_version"], enc["ciphertext"])
    return {
        "status": "ok" if dec == payload else "mismatch",
        "key_version": enc["key_version"],
        "ciphertext_len": len(enc["ciphertext"]),
    }


class GovProfileIn(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    data_residency_region: str | None = Field(default=None, max_length=40)
    dsr_contact_email: str | None = Field(default=None, max_length=320)


class GovPurgeIn(BaseModel):
    organization_id: str | None = None
    dry_run: bool = True

# ------------------------------------------------------------------ PROMPT 12
# Customer Success

@router.get("/customer-success/conversion", summary="Funnel trial → paid")
async def platform_cs_conversion(request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.customer_success.customer_success import conversion_analytics

    return await conversion_analytics()


@router.get("/customer-success/onboarding", summary="Onboarding de un tenant")
async def platform_cs_onboarding(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.customer_success.customer_success import onboarding_checklist

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE status <> 'deleted'")
                )
            ).fetchall()
        finally:
            await session.close()
        return {"organizations": [await onboarding_checklist(r.id) for r in rows]}
    return await onboarding_checklist(oid)


@router.get("/customer-success/reports", summary="Suscripciones a reportes de uso")
async def platform_cs_reports(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.customer_success.customer_success import list_report_subscriptions

    oid = UUID(organization_id) if organization_id else None
    subs = await list_report_subscriptions(oid)
    return {"subscriptions": subs, "count": len(subs)}


@router.post("/customer-success/reports", status_code=201, summary="Suscribir reporte de uso")
async def platform_cs_reports_post(body: ReportSubscribeIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.customer_success.customer_success import subscribe_report

    oid = _parse_org(body.organization_id)
    return await subscribe_report(oid, body.email, body.frequency)


@router.post("/customer-success/reports/{sub_id}/send-now", summary="Enviar reporte ahora")
async def platform_cs_reports_send(sub_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.customer_success.customer_success import send_report_now

    return await send_report_now(UUID(sub_id))


@router.delete("/customer-success/reports/{sub_id}", summary="Cancelar suscripción de reporte")
async def platform_cs_reports_delete(sub_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.customer_success.customer_success import unsubscribe_report

    ok = await unsubscribe_report(UUID(sub_id))
    if not ok:
        raise HTTPException(404, "Subscription not found")
    return {"status": "deleted"}


class ReportSubscribeIn(BaseModel):
    organization_id: str
    email: str = Field(..., max_length=320)
    frequency: str = Field(default="monthly", pattern="^(weekly|monthly)$")

# ------------------------------------------------------------------ PROMPT 13
# Audit Intelligence & AI Governance

@router.get("/audit-intelligence/summary", summary="Resumen de auditoría")
async def platform_ai_summary(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "audit.read")
    from src.platform.ai_governance.ai_governance import audit_intelligence

    oid = UUID(organization_id) if organization_id else None
    return await audit_intelligence(oid)


@router.post("/audit-intelligence/check", summary="Ejecutar detección de anomalías")
async def platform_ai_check(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.ai_governance.ai_governance import run_anomaly_checks

    oid = UUID(organization_id) if organization_id else None
    created = await run_anomaly_checks(oid)
    return {"anomalies_created": created, "count": len(created)}


@router.get("/audit-intelligence/anomalies", summary="Anomalías detectadas")
async def platform_ai_anomalies(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.ai_governance.ai_governance import list_anomalies

    oid = UUID(organization_id) if organization_id else None
    anomalies = await list_anomalies(oid, status=status, limit=min(limit, 200))
    return {"anomalies": anomalies, "count": len(anomalies)}


@router.post("/audit-intelligence/anomalies/{anomaly_id}/resolve", summary="Resolver anomalía")
async def platform_ai_anomaly_resolve(anomaly_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.ai_governance.ai_governance import resolve_anomaly

    ok = await resolve_anomaly(UUID(anomaly_id))
    if not ok:
        raise HTTPException(404, "Anomaly not found or already resolved")
    return {"status": "resolved"}


@router.get("/ai-governance/organizations/{org_id}", summary="Políticas AI del tenant")
async def platform_ai_policies_get(org_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.ai_governance.ai_governance import get_ai_policies

    oid = _parse_org(org_id)
    return await get_ai_policies(oid)


@router.put("/ai-governance/organizations/{org_id}", summary="Guardar políticas AI")
async def platform_ai_policies_put(org_id: str, body: AiPoliciesIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.ai_governance.ai_governance import set_ai_policies

    oid = _parse_org(org_id)
    await set_ai_policies(
        oid,
        pii_masking_enabled=body.pii_masking_enabled,
        guardrails=body.guardrails,
    )
    return {"status": "saved", "organization_id": str(oid)}


@router.post("/ai-governance/pii/mask", summary="Enmascarar PII de un texto")
async def platform_ai_pii_mask(body: PiiTextIn, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.ai_governance.ai_governance import mask_pii

    masked, counts = mask_pii(body.text)
    return {"masked": masked, "detected": counts}


@router.post("/ai-governance/pii/scan", summary="Escanear PII de un texto")
async def platform_ai_pii_scan(body: PiiTextIn, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.ai_governance.ai_governance import scan_pii

    return {"detected": scan_pii(body.text)}


@router.get("/ai-governance/prompts/{prompt_key}/revisions", summary="Revisions de un prompt")
async def platform_ai_prompt_revisions(
    prompt_key: str,
    request: Request,
    organization_id: str | None = None,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.ai_governance.ai_governance import list_prompt_revisions

    oid = UUID(organization_id) if organization_id else None
    return {"revisions": await list_prompt_revisions(prompt_key, oid)}


class AiPoliciesIn(BaseModel):
    pii_masking_enabled: bool | None = None
    guardrails: dict | None = None


class PiiTextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=100000)

# ------------------------------------------------------------------ PROMPT 14
# Performance & Cost Optimizer

@router.get("/optimizer/profiles", summary="Perfiles de costo/desempeño por agente")
async def platform_optimizer_profiles(
    request: Request,
    organization_id: str | None = None,
    deployment_id: str | None = None,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.optimizer.optimizer import agent_profiles, deployment_profile

    oid = UUID(organization_id) if organization_id else None
    if deployment_id:
        if oid is None:
            raise HTTPException(400, "organization_id requerido con deployment_id")
        profile = await deployment_profile(oid, UUID(deployment_id))
        if profile is None:
            raise HTTPException(404, "Deployment not found")
        return profile
    if oid is None:
        session = await get_async_session()
        try:
            rows = (
                await session.execute(
                    text("SELECT id FROM organizations WHERE status <> 'deleted'")
                )
            ).fetchall()
        finally:
            await session.close()
        return {"organizations": [await agent_profiles(r.id) for r in rows]}
    return {"profiles": await agent_profiles(oid)}


@router.post("/optimizer/scan", summary="Escanear y generar recomendaciones")
async def platform_optimizer_scan(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.optimizer.optimizer import scan

    oid = UUID(organization_id) if organization_id else None
    created = await scan(oid)
    return {"recommendations_created": created, "count": len(created)}


@router.get("/optimizer/recommendations", summary="Recomendaciones del optimizer")
async def platform_optimizer_recommendations(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.optimizer.optimizer import list_recommendations

    oid = UUID(organization_id) if organization_id else None
    recs = await list_recommendations(oid, status=status, limit=min(limit, 300))
    return {"recommendations": recs, "count": len(recs)}


@router.post("/optimizer/recommendations/{rec_id}/apply", summary="Aplicar recomendación")
async def platform_optimizer_apply(rec_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.optimizer.optimizer import apply_recommendation

    result = await apply_recommendation(UUID(rec_id))
    if result["status"] == "not_found":
        raise HTTPException(404, "Recommendation not found")
    return result


@router.post("/optimizer/recommendations/{rec_id}/ignore", summary="Ignorar recomendación")
async def platform_optimizer_ignore(rec_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.optimizer.optimizer import ignore_recommendation

    ok = await ignore_recommendation(UUID(rec_id))
    if not ok:
        raise HTTPException(404, "Recommendation not found or already processed")
    return {"status": "ignored"}

# ------------------------------------------------------------------ PROMPT 15
# Federated Analytics (multi-tenant)

@router.get("/analytics/federated", summary="Métricas multi-tenant agregadas")
async def platform_fed_analytics(request: Request, format: str | None = None):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.analytics.federated import export_federated_analytics, federated_analytics

    if format in ("csv", "json"):
        return await export_federated_analytics(format=format)
    return await federated_analytics()


@router.get("/analytics/organizations/{org_id}", summary="Drill-down de un tenant")
async def platform_org_analytics(org_id: str, request: Request, format: str | None = None):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.analytics.federated import export_organization_analytics, organization_analytics

    oid = _parse_org(org_id)
    if format in ("csv", "json"):
        return await export_organization_analytics(oid, format=format)
    return await organization_analytics(oid)

# ------------------------------------------------------------------ PROMPT 16
# Marketplace & Sharing

@router.get("/marketplace/listings", summary="Listar listings del marketplace")
async def platform_mkt_listings(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    status: str = "published",
    limit: int = 50,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.marketplace.marketplace import list_listings

    listings = await list_listings(q=q, category=category, status=status, limit=limit)
    return {"listings": listings, "count": len(listings)}


@router.post("/marketplace/listings", status_code=201, summary="Publicar agente al marketplace")
async def platform_mkt_publish(body: MktPublishIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import publish_agent

    oid = _parse_org(body.organization_id)
    result = await publish_agent(
        oid, UUID(body.agent_id), body.name, body.description, body.category, body.tags
    )
    if result["status"] == "agent_not_found":
        raise HTTPException(404, "Agent not found")
    return result


@router.post("/marketplace/listings/{listing_id}/unpublish", summary="Quitar del marketplace")
async def platform_mkt_unpublish(listing_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import unpublish_listing

    ok = await unpublish_listing(UUID(listing_id))
    if not ok:
        raise HTTPException(404, "Listing not found")
    return {"status": "unpublished"}


@router.get("/marketplace/listings/{listing_id}", summary="Detalle de listing con snapshot")
async def platform_mkt_detail(listing_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.marketplace.marketplace import get_listing

    listing = await get_listing(UUID(listing_id))
    if listing is None:
        raise HTTPException(404, "Listing not found")
    return listing


@router.post("/marketplace/listings/{listing_id}/reviews", summary="Publicar review de listing")
async def platform_mkt_review(listing_id: str, body: MktReviewIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import add_review

    oid = _parse_org(body.organization_id)
    return await add_review(UUID(listing_id), oid, body.rating, body.comment)


@router.get("/marketplace/listings/{listing_id}/reviews", summary="Reviews de un listing")
async def platform_mkt_reviews(listing_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.marketplace.marketplace import list_reviews

    return {"reviews": await list_reviews(UUID(listing_id))}


@router.post("/marketplace/listings/{listing_id}/install", summary="Instalar (clonar) en una org")
async def platform_mkt_install(listing_id: str, body: MktInstallIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import install_listing

    oid = _parse_org(body.organization_id)
    return await install_listing(UUID(listing_id), oid)


@router.get("/marketplace/templates", summary="Prompt templates del repositorio")
async def platform_mkt_templates(request: Request, category: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.marketplace.marketplace import list_templates

    return {"templates": await list_templates(category=category)}


@router.post("/marketplace/templates", status_code=201, summary="Crear prompt template")
async def platform_mkt_template_create(body: TemplateIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import create_template

    return await create_template(
        body.name, body.category, body.description, body.content, created_by=ctx.user_id
    )


@router.put("/marketplace/templates/{template_id}", summary="Actualizar prompt template")
async def platform_mkt_template_update(template_id: str, body: TemplateIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import update_template

    ok = await update_template(
        UUID(template_id),
        name=body.name,
        category=body.category,
        description=body.description,
        content=body.content,
    )
    if not ok:
        raise HTTPException(404, "Template not found")
    return {"status": "updated"}


@router.delete("/marketplace/templates/{template_id}", summary="Eliminar prompt template")
async def platform_mkt_template_delete(template_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.marketplace.marketplace import delete_template

    ok = await delete_template(UUID(template_id))
    if not ok:
        raise HTTPException(404, "Template not found or builtin")
    return {"status": "deleted"}


class MktPublishIn(BaseModel):
    organization_id: str
    agent_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    category: str = Field(default="general", max_length=60)
    tags: list[str] = Field(default_factory=list)


class MktReviewIn(BaseModel):
    organization_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class MktInstallIn(BaseModel):
    organization_id: str


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="general", max_length=60)
    description: str | None = None
    content: str = Field(..., min_length=1)

# ------------------------------------------------------------------ PROMPT 17
# Workflows (platform overview)

@router.post("/workflows", status_code=201, summary="Crear workflow para un tenant")
async def platform_workflow_create(body: PlatformWorkflowIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.workflows.workflows import create_definition

    oid = _parse_org(body.organization_id)
    try:
        result = await create_definition(
            oid,
            body.name,
            body.description,
            body.trigger_type,
            body.cron_expr,
            [s.model_dump() for s in body.steps],
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.get("/workflows", summary="Workflows de todos los tenants")
async def platform_workflows(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.workflows.workflows import list_definitions

    oid = UUID(organization_id) if organization_id else None
    return {"workflows": await list_definitions(oid, limit=200)}


@router.post("/workflows/{workflow_id}/trigger", summary="Disparar workflow de un tenant")
async def platform_workflow_trigger(workflow_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.workflows.workflows import trigger_workflow

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id FROM workflow_definitions WHERE id = :wid"),
                {"wid": UUID(workflow_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "Workflow not found")
    result = await trigger_workflow(row.organization_id, UUID(workflow_id), trigger="manual")
    if result["status"] == "not_found":
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/workflows/runs", summary="Runs de workflows (global)")
async def platform_workflow_runs(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.workflows.workflows import list_runs

    oid = UUID(organization_id) if organization_id else None
    runs = await list_runs(oid, status=status, limit=min(limit, 300))
    return {"runs": runs, "count": len(runs)}
class PlatformWorkflowStepIn(BaseModel):
    type: str = Field(..., pattern="^(ingest|evaluate|deploy|notify|webhook|approval)$")
    params: dict = Field(default_factory=dict)


class PlatformWorkflowIn(BaseModel):
    organization_id: str
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str = Field(default="manual", pattern="^(manual|schedule|event)$")
    cron_expr: str | None = None
    steps: list[PlatformWorkflowStepIn] = Field(default_factory=list, min_length=1)

# ------------------------------------------------------------------ PROMPT 18
# Model Gateway & Cost Routing

@router.get("/model-gateway/routes", summary="Rutas de modelos por org")
async def platform_gw_routes(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.model_gateway.gateway import list_routes

    oid = UUID(organization_id) if organization_id else None
    routes = await list_routes(oid)
    return {"routes": routes, "count": len(routes)}


@router.post("/model-gateway/routes", status_code=201, summary="Crear ruta de modelo")
async def platform_gw_route_create(body: ModelRouteIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.model_gateway.gateway import create_route

    oid = _parse_org(body.organization_id)
    try:
        return await create_route(
            oid, body.name, body.condition_type, body.condition_value,
            body.model, body.traffic_pct, body.priority,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.put("/model-gateway/routes/{route_id}", summary="Actualizar ruta de modelo")
async def platform_gw_route_update(route_id: str, body: ModelRouteIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.model_gateway.gateway import update_route

    oid = _parse_org(body.organization_id)
    ok = await update_route(
        oid, UUID(route_id),
        name=body.name,
        condition_type=body.condition_type,
        condition_value=body.condition_value,
        model=body.model,
        traffic_pct=body.traffic_pct,
        priority=body.priority,
        active=body.active,
    )
    if not ok:
        raise HTTPException(404, "Route not found")
    return {"status": "updated"}


@router.delete("/model-gateway/routes/{route_id}", summary="Eliminar ruta de modelo")
async def platform_gw_route_delete(route_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.model_gateway.gateway import delete_route

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id FROM model_routes WHERE id = :rid"),
                {"rid": UUID(route_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "Route not found")
    await delete_route(row.organization_id, UUID(route_id))
    return {"status": "deleted"}


@router.get("/model-gateway/budgets", summary="Presupuestos por modelo")
async def platform_gw_budgets(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.model_gateway.gateway import list_budgets

    oid = UUID(organization_id) if organization_id else None
    budgets = await list_budgets(oid)
    return {"budgets": budgets, "count": len(budgets)}


@router.post("/model-gateway/budgets", status_code=201, summary="Fijar presupuesto de modelo")
async def platform_gw_budget_create(body: ModelBudgetIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.model_gateway.gateway import create_budget

    oid = _parse_org(body.organization_id)
    return await create_budget(oid, body.model, body.monthly_budget_cents)


@router.delete("/model-gateway/budgets/{budget_id}", summary="Quitar presupuesto de modelo")
async def platform_gw_budget_delete(budget_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.model_gateway.gateway import delete_budget

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id FROM model_budgets WHERE id = :bid"),
                {"bid": UUID(budget_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "Budget not found")
    await delete_budget(row.organization_id, UUID(budget_id))
    return {"status": "deleted"}


@router.get("/model-gateway/analytics", summary="Analytics del gateway por modelo")
async def platform_gw_analytics(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.model_gateway.gateway import gateway_analytics

    oid = UUID(organization_id) if organization_id else None
    return await gateway_analytics(oid)


class ModelRouteIn(BaseModel):
    organization_id: str
    name: str = Field(..., min_length=1, max_length=120)
    condition_type: str = Field(default="default", max_length=20)
    condition_value: float | None = None
    model: str = Field(..., min_length=1, max_length=120)
    traffic_pct: int = Field(default=100, ge=1, le=100)
    priority: int = Field(default=0)
    active: bool = True


class ModelBudgetIn(BaseModel):
    organization_id: str
    model: str = Field(..., min_length=1, max_length=120)
    monthly_budget_cents: int = Field(..., ge=1)

# ------------------------------------------------------------------ PROMPT 19
# Real-Time Analytics & Streaming

@router.get("/realtime/stream", summary="Stream SSE de eventos en vivo")
async def platform_realtime_stream(
    request: Request,
    organization_id: str | None = None,
):
    ctx = require_platform_permission(request, "operations.read")
    from fastapi.responses import StreamingResponse

    from src.platform.realtime.stream import event_source

    async def gen():
        async for chunk in event_source(organization_id=organization_id):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.get("/realtime/summary", summary="Resumen en vivo (ventana reciente)")
async def platform_realtime_summary(request: Request, minutes: int = 15):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.realtime.stream import live_summary

    return await live_summary(minutes)


@router.get("/realtime/timeseries", summary="Series temporales de uso")
async def platform_realtime_timeseries(
    request: Request, hours: int = 24, format: str = "json"
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.realtime.stream import timeseries

    return await timeseries(hours, format=format)


@router.post("/realtime/auto-correction", summary="Activar/desactivar corrección automática")
async def platform_realtime_auto_correction(body: AutoCorrectionIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.realtime.stream import set_auto_correction

    set_auto_correction(body.enabled)
    return {"status": "saved", "enabled": body.enabled}


@router.get("/realtime/auto-correction", summary="Estado de la corrección automática")
async def platform_realtime_auto_correction_get(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.realtime.stream import auto_correction_enabled

    return {"enabled": auto_correction_enabled()}


class AutoCorrectionIn(BaseModel):
    enabled: bool

# ------------------------------------------------------------------ PROMPT 20
# Security Center

@router.get("/security/posture", summary="Posture score por tenant")
async def platform_sec_posture(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.security.posture import posture_for_all, posture_score

    oid = UUID(organization_id) if organization_id else None
    if oid is None:
        return {"organizations": await posture_for_all()}
    return await posture_score(oid)


@router.post("/security/scan", summary="Escanear secretos y leaks")
async def platform_sec_scan(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.security.posture import run_security_scan

    oid = UUID(organization_id) if organization_id else None
    return await run_security_scan(oid)


@router.post("/security/scan-secrets", summary="Escanear secretos de un texto")
async def platform_sec_scan_secrets(body: SecTextIn, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.security.posture import scan_secrets

    return {"detected": scan_secrets(body.text)}


@router.get("/security/findings", summary="Findings de seguridad")
async def platform_sec_findings(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.security.posture import list_findings

    oid = UUID(organization_id) if organization_id else None
    findings = await list_findings(oid, status=status, limit=min(limit, 300))
    return {"findings": findings, "count": len(findings)}


@router.post("/security/findings/{finding_id}/resolve", summary="Resolver finding")
async def platform_sec_finding_resolve(finding_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.security.posture import resolve_finding

    ok = await resolve_finding(UUID(finding_id))
    if not ok:
        raise HTTPException(404, "Finding not found or already resolved")
    return {"status": "resolved"}


@router.post("/security/keys/{key_id}/revoke", summary="Revocar key señalada (one-click)")
async def platform_sec_key_revoke(key_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.security.posture import revoke_leaked_key

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text("SELECT organization_id FROM api_keys WHERE id = :kid"),
                {"kid": UUID(key_id)},
            )
        ).fetchone()
    finally:
        await session.close()
    if row is None:
        raise HTTPException(404, "Key not found")
    ok = await revoke_leaked_key(row.organization_id, UUID(key_id))
    if not ok:
        raise HTTPException(404, "Key not found")
    return {"status": "revoked", "key_id": key_id}


class SecTextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=100000)

# ------------------------------------------------------------------ PROMPT 21
# Onboarding & Tenancy Self-Serve

@router.get("/onboarding/plans", summary="Catálogo de planes para el wizard")
async def platform_onboarding_plans(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT name, display_name, price_monthly_cents, requests_per_month, "
                    "is_trial, trial_days FROM plans WHERE is_public = true OR is_trial = true "
                    "ORDER BY price_monthly_cents"
                )
            )
        ).fetchall()
    finally:
        await session.close()
    return {"plans": [dict(r._mapping) for r in rows]}


@router.post("/onboarding/provision", status_code=201, summary="Provisionar tenant en 1 clic")
async def platform_onboarding_provision(body: ProvisionIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.onboarding.provision import provision_tenant

    try:
        return await provision_tenant(
            company_name=body.company_name,
            email=body.email,
            plan_name=body.plan_name,
            with_demo=body.with_demo,
            sso_issuer=body.sso_issuer,
            sso_client_id=body.sso_client_id,
            sso_client_secret=body.sso_client_secret,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/onboarding/migrate", summary="Migrar KBs y agentes entre tenants")
async def platform_onboarding_migrate(body: MigrateIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.onboarding.provision import migrate_tenant

    result = await migrate_tenant(
        _parse_org(body.source_organization_id),
        _parse_org(body.target_organization_id),
        migrate_kbs=body.migrate_kbs,
        migrate_agents=body.migrate_agents,
    )
    if result["status"] == "target_not_found":
        raise HTTPException(404, "Organización destino no encontrada")
    return result


@router.post("/onboarding/extend-trial", summary="Extender trial auto-aprobado")
async def platform_onboarding_extend(body: ExtendTrialIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.onboarding.provision import extend_trial

    result = await extend_trial(_parse_org(body.organization_id), body.days)
    if result["status"] == "not_trialing":
        raise HTTPException(400, "La organización no está en trial")
    return result


class ProvisionIn(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    email: str = Field(..., min_length=5, max_length=320)
    plan_name: str = Field(default="trial", max_length=100)
    with_demo: bool = False
    sso_issuer: str | None = None
    sso_client_id: str | None = None
    sso_client_secret: str | None = None


class MigrateIn(BaseModel):
    source_organization_id: str
    target_organization_id: str
    migrate_kbs: bool = True
    migrate_agents: bool = True


class ExtendTrialIn(BaseModel):
    organization_id: str
    days: int = Field(..., ge=1, le=90)

# ------------------------------------------------------------------ PROMPT 22
# Capacity Planning & Auto-Scaling

@router.get("/capacity/summary", summary="Resumen global de capacidad")
async def platform_capacity_summary(request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.capacity.planning import capacity_summary

    return await capacity_summary()


@router.get("/capacity/organizations/{org_id}", summary="Capacidad y forecast de un tenant")
async def platform_capacity_org(org_id: str, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.capacity.planning import capacity_status

    oid = _parse_org(org_id)
    return await capacity_status(oid)


@router.post("/capacity/simulate", summary="Simular crecimiento de costo")
async def platform_capacity_simulate(body: CapacitySimulateIn, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.capacity.planning import simulate_growth

    oid = _parse_org(body.organization_id)
    return await simulate_growth(oid, body.growth_pct, body.days)


@router.get("/capacity/queues", summary="Profundidad de las colas")
async def platform_capacity_queues(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.capacity.planning import queue_depths

    return {"queues": await queue_depths()}


@router.post("/capacity/workers/scale", summary="Escalar workers manualmente")
async def platform_capacity_scale(body: CapacityScaleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.capacity.planning import record_scaling_event

    await record_scaling_event(
        body.queue, "manual_scale", depth=body.depth, target=body.target,
        reason=f"escalado manual a {body.target} workers",
    )
    return {"status": "scheduled", "queue": body.queue, "target": body.target}


@router.post("/capacity/workers/auto-scale", summary="Activar auto-scaling")
async def platform_capacity_auto_scale(body: AutoScaleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.capacity.planning import set_auto_scale

    set_auto_scale(body.enabled)
    return {"status": "saved", "enabled": body.enabled}


@router.get("/capacity/workers/auto-scale", summary="Estado del auto-scaling")
async def platform_capacity_auto_scale_get(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.capacity.planning import auto_scale_enabled

    return {"enabled": auto_scale_enabled()}


class CapacitySimulateIn(BaseModel):
    organization_id: str
    growth_pct: float = Field(..., ge=-50, le=500)
    days: int = Field(default=30, ge=1, le=365)


class CapacityScaleIn(BaseModel):
    queue: str = Field(..., max_length=60)
    target: int = Field(..., ge=1, le=64)
    depth: int = 0


class AutoScaleIn(BaseModel):
    enabled: bool

# ------------------------------------------------------------------ PROMPT 23
# Developer Experience

@router.get("/dev/sdk-reference", summary="Referencia SDK auto-generada")
async def platform_dev_sdk(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.devportal.sdk import sdk_reference

    return await sdk_reference()


@router.get("/dev/changelog", summary="Changelog del platform")
async def platform_dev_changelog(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.devportal.sdk import list_changelog

    entries = await list_changelog(public_only=False)
    return {"changelog": entries, "count": len(entries)}


@router.post("/dev/changelog", status_code=201, summary="Publicar entrada de changelog")
async def platform_dev_changelog_add(body: ChangelogIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.devportal.sdk import add_changelog

    return await add_changelog(body.version, body.title, body.body, body.is_public)


@router.get("/dev/status", summary="Estado público del platform (devs)")
async def platform_dev_status(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.devportal.sdk import platform_status

    return await platform_status()


class ChangelogIn(BaseModel):
    version: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1)
    is_public: bool = True

# ------------------------------------------------------------------ PROMPT 24
# Partner Ecosystem

@router.get("/partners", summary="Listar partners")
async def platform_partners_list(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.partners.partners import list_partners

    partners = await list_partners()
    return {"partners": partners, "count": len(partners)}


@router.post("/partners", status_code=201, summary="Crear partner (devuelve token dedicado)")
async def platform_partners_create(body: PartnerIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import create_partner

    oid = _parse_org(body.organization_id)
    return await create_partner(oid, body.name, body.contact_email, body.rev_share_pct)


@router.put("/partners/{partner_id}", summary="Actualizar partner")
async def platform_partners_update(partner_id: str, body: PartnerIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import update_partner

    ok = await update_partner(
        UUID(partner_id),
        name=body.name,
        contact_email=body.contact_email,
        rev_share_pct=body.rev_share_pct,
        white_label_enabled=body.white_label_enabled,
    )
    if not ok:
        raise HTTPException(404, "Partner not found")
    return {"status": "updated"}


@router.post("/partners/{partner_id}/status", summary="Activar/suspender partner")
async def platform_partners_status(partner_id: str, body: PartnerStatusIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import set_partner_status

    ok = await set_partner_status(UUID(partner_id), body.status)
    if not ok:
        raise HTTPException(404, "Partner not found")
    return {"status": "saved", "status_value": body.status}


@router.get("/partners/{partner_id}/usage", summary="Uso del partner (30d)")
async def platform_partners_usage(partner_id: str, request: Request, days: int = 30):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.partners.partners import partner_usage

    return await partner_usage(UUID(partner_id), days)


@router.post("/partners/{partner_id}/commission/calculate", summary="Calcular comisión del período")
async def platform_partners_commission(partner_id: str, body: CommissionIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import calculate_commission

    result = await calculate_commission(UUID(partner_id), body.period)
    if result["status"] == "not_found":
        raise HTTPException(404, "Partner not found")
    return result


@router.get("/partners/{partner_id}/commissions", summary="Comisiones del partner")
async def platform_partners_commissions(partner_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.partners.partners import list_commissions

    return {"commissions": await list_commissions(UUID(partner_id))}


@router.post("/partners/{partner_id}/subtenants", status_code=201, summary="Adjuntar subtenant")
async def platform_partners_subtenant(partner_id: str, body: SubtenantIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import attach_subtenant

    oid = _parse_org(body.organization_id)
    result = await attach_subtenant(UUID(partner_id), oid, body.commission_share_pct)
    if result["status"] == "org_not_found":
        raise HTTPException(404, "Organización no encontrada")
    return result


@router.get("/partners/{partner_id}/subtenants", summary="Subtenants del partner")
async def platform_partners_subtenants(partner_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.partners.partners import list_subtenants

    subtenants = await list_subtenants(UUID(partner_id))
    return {"subtenants": subtenants, "count": len(subtenants)}


@router.put("/partners/{partner_id}/branding", summary="Branding white-label")
async def platform_partners_branding(partner_id: str, body: PartnerBrandingIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import set_partner_branding

    ok = await set_partner_branding(UUID(partner_id), body.branding)
    if not ok:
        raise HTTPException(404, "Partner not found")
    return {"status": "saved"}


@router.get("/partners/integrations", summary="Catálogo de integraciones")
async def platform_partners_integrations(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.partners.partners import list_integrations

    integrations = await list_integrations()
    return {"integrations": integrations, "count": len(integrations)}


@router.post("/partners/integrations", status_code=201, summary="Añadir integración al catálogo")
async def platform_partners_integration_add(body: IntegrationIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import add_integration

    return await add_integration(body.key, body.name, body.category, body.description, body.oauth_url_template)


@router.put("/partners/integrations/{key}", summary="Activar/desactivar integración")
async def platform_partners_integration_toggle(key: str, body: IntegrationToggleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.partners.partners import toggle_integration

    ok = await toggle_integration(key, body.active)
    if not ok:
        raise HTTPException(404, "Integración no encontrada")
    return {"status": "saved", "active": body.active}


class PartnerIn(BaseModel):
    organization_id: str
    name: str = Field(..., min_length=1, max_length=200)
    contact_email: str | None = Field(default=None, max_length=320)
    rev_share_pct: float = Field(default=10.0, ge=0, le=100)
    white_label_enabled: bool = False


class PartnerStatusIn(BaseModel):
    status: str = Field(..., pattern="^(active|suspended)$")


class CommissionIn(BaseModel):
    period: str = Field(..., pattern="^\\d{4}-\\d{2}$")


class SubtenantIn(BaseModel):
    organization_id: str
    commission_share_pct: float = Field(default=100.0, ge=0, le=100)


class PartnerBrandingIn(BaseModel):
    branding: dict = Field(default_factory=dict)


class IntegrationIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=60)
    name: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="general", max_length=60)
    description: str | None = None
    oauth_url_template: str | None = None


class IntegrationToggleIn(BaseModel):
    active: bool

# ------------------------------------------------------------------ PROMPT 25
# AI Quality & Evals v2


def _get_agent_runtime_dep():
    from src.api.deps import get_agent_runtime

    return get_agent_runtime

@router.get("/evals/datasets", summary="Datasets de evaluación")
async def platform_evals_datasets(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.evals.evals import list_datasets

    oid = UUID(organization_id) if organization_id else None
    datasets = await list_datasets(oid)
    return {"datasets": datasets, "count": len(datasets)}


@router.post("/evals/datasets", status_code=201, summary="Crear dataset de evaluación")
async def platform_evals_dataset_create(body: EvalDatasetIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.evals.evals import create_dataset

    oid = _parse_org(body.organization_id)
    return await create_dataset(oid, body.name, body.description, created_by=ctx.user_id)


@router.post("/evals/datasets/{dataset_id}/items", status_code=201, summary="Añadir items (bump versión)")
async def platform_evals_items_add(dataset_id: str, body: EvalItemsIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.evals.evals import add_dataset_items

    result = await add_dataset_items(
        UUID(dataset_id), [i.model_dump() for i in body.items]
    )
    if result["status"] == "not_found":
        raise HTTPException(404, "Dataset not found")
    return result


@router.get("/evals/datasets/{dataset_id}/items", summary="Items de un dataset")
async def platform_evals_items(dataset_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.evals.evals import list_items

    return {"items": await list_items(UUID(dataset_id))}


@router.post("/evals/runs", status_code=201, summary="Ejecutar evaluación (run)")
async def platform_evals_run(body: EvalRunIn, request: Request, runtime=Depends(_get_agent_runtime_dep())):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.evals.evals import trigger_run

    oid = _parse_org(body.organization_id)
    result = await trigger_run(
        oid, UUID(body.dataset_id), UUID(body.agent_id), runtime,
        auto_promote=body.auto_promote, auto_rollback=body.auto_rollback,
        created_by=ctx.user_id,
    )
    if result["status"] in ("dataset_not_found", "agent_not_found"):
        raise HTTPException(404, result["status"])
    return result


@router.get("/evals/runs", summary="Runs de evaluación")
async def platform_evals_runs(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.evals.evals import list_runs

    oid = UUID(organization_id) if organization_id else None
    runs = await list_runs(oid, status=status, limit=min(limit, 200))
    return {"runs": runs, "count": len(runs)}


@router.get("/evals/runs/{run_id}", summary="Detalle de un run (items)")
async def platform_evals_run_detail(run_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.evals.evals import get_run_detail

    detail = await get_run_detail(UUID(run_id))
    if detail is None:
        raise HTTPException(404, "Run not found")
    return detail




class EvalDatasetIn(BaseModel):
    organization_id: str
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class EvalItemIn(BaseModel):
    question: str = Field(..., min_length=1)
    expected_answer: str = Field(..., min_length=1)
    context: str | None = None
    score_weight: float = Field(default=1.0, ge=0.0, le=10.0)


class EvalItemsIn(BaseModel):
    items: list[EvalItemIn] = Field(..., min_length=1)


class EvalRunIn(BaseModel):
    organization_id: str
    dataset_id: str
    agent_id: str
    auto_promote: bool = False
    auto_rollback: bool = False

# ------------------------------------------------------------------ PROMPT 26
# Usage Metering & Rate Limits v2

@router.get("/metering/realtime", summary="Contadores en tiempo real")
async def platform_metering_realtime(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.metering.metering import realtime

    oid = UUID(organization_id) if organization_id else None
    return await realtime(oid)


@router.get("/metering/throttle", summary="Fair-use / throttling dinámico")
async def platform_metering_throttle(request: Request, organization_id: str):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.metering.metering import throttle_factor

    oid = _parse_org(organization_id)
    return await throttle_factor(oid)


@router.get("/rate-limits/rules", summary="Reglas de rate limit por plan")
async def platform_rate_limits_rules(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.metering.metering import list_rules

    rules = await list_rules()
    return {"rules": rules, "count": len(rules)}


@router.post("/rate-limits/rules", status_code=201, summary="Crear regla de rate limit")
async def platform_rate_limits_rule_create(body: RateLimitRuleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.metering.metering import create_rule

    return await create_rule(
        body.plan_name, body.endpoint_prefix, body.limit_per_minute, body.burst, body.priority
    )


@router.put("/rate-limits/rules/{rule_id}", summary="Actualizar regla")
async def platform_rate_limits_rule_update(rule_id: str, body: RateLimitRuleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.metering.metering import update_rule

    ok = await update_rule(
        UUID(rule_id),
        plan_name=body.plan_name,
        endpoint_prefix=body.endpoint_prefix,
        limit_per_minute=body.limit_per_minute,
        burst=body.burst,
        priority=body.priority,
        enabled=body.enabled,
    )
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"status": "updated"}


@router.delete("/rate-limits/rules/{rule_id}", summary="Eliminar regla")
async def platform_rate_limits_rule_delete(rule_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.metering.metering import delete_rule

    ok = await delete_rule(UUID(rule_id))
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"status": "deleted"}


@router.get("/rate-limits/rules/effective", summary="Límites efectivos de un org (con throttle)")
async def platform_rate_limits_effective(request: Request, organization_id: str, path: str = "/"):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.metering.metering import effective_limits

    oid = _parse_org(organization_id)
    return await effective_limits(oid, path)


class RateLimitRuleIn(BaseModel):
    plan_name: str | None = Field(default=None, max_length=50)
    endpoint_prefix: str = Field(default="/", max_length=120)
    limit_per_minute: int = Field(..., ge=1, le=10000)
    burst: int = Field(default=10, ge=0, le=5000)
    priority: int = 0
    enabled: bool = True

# ------------------------------------------------------------------ PROMPT 27
# Multitenant LLM Proxy

@router.get("/proxy/models", summary="Catálogo de modelos del proxy")
async def platform_proxy_models(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.proxy.inference_proxy import list_models

    return await list_models()


@router.post("/proxy/models", status_code=201, summary="Upsert modelo del proxy")
async def platform_proxy_model_upsert(body: ProxyModelIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.proxy.inference_proxy import upsert_model

    return await upsert_model(body.model_name, body.backend, body.capacity, body.status)


@router.get("/proxy/inference-logs", summary="Logs de inferencia")
async def platform_proxy_logs(
    request: Request,
    organization_id: str | None = None,
    deployment_id: str | None = None,
    model: str | None = None,
    hours: int = 24,
    limit: int = 100,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.proxy.inference_proxy import list_logs

    return await list_logs(
        UUID(organization_id) if organization_id else None,
        UUID(deployment_id) if deployment_id else None,
        model,
        hours,
        min(max(limit, 1), 500),
    )


@router.get("/proxy/performance", summary="Performance por modelo (p95, throughput)")
async def platform_proxy_performance(request: Request, model: str | None = None, hours: int = 24):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.proxy.inference_proxy import performance

    return await performance(model, hours)


@router.get("/proxy/queue", summary="Cola viva por plan y modelo")
async def platform_proxy_queue(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.proxy.inference_proxy import queue_snapshot

    return await queue_snapshot()


class ProxyModelIn(BaseModel):
    model_name: str = Field(..., max_length=120)
    backend: str = Field(default="openai", max_length=20)
    capacity: int = Field(default=50, ge=1, le=100000)
    status: str = Field(default="active", max_length=20)

# ------------------------------------------------------------------ PROMPT 28
# Multi-Region & Edge Caching

@router.get("/regions", summary="Regiones y réplicas con health")
async def platform_regions(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.edge.multiregion import region_status

    return await region_status()


@router.get("/regions/latency", summary="Latencia por región (inference_logs)")
async def platform_regions_latency(request: Request, hours: int = 24):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.edge.multiregion import latency_by_region

    return await latency_by_region(hours)


@router.get("/regions/resolve", summary="Región resuelta de un org (con failover)")
async def platform_regions_resolve(request: Request, organization_id: str):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.edge.multiregion import resolve_region

    oid = _parse_org(organization_id)
    return await resolve_region(oid)


@router.post("/regions/{region_code}/failover", summary="Simular failover de una región")
async def platform_regions_failover(region_code: str, request: Request, organization_id: str):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.edge.multiregion import resolve_region, set_region_health

    await set_region_health(region_code, False)
    oid = _parse_org(organization_id)
    resolution = await resolve_region(oid)
    return {"simulated_unhealthy": region_code, "resolution": resolution}


@router.post("/regions/healthcheck", summary="Forzar healthcheck de réplicas")
async def platform_regions_healthcheck(request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.edge.multiregion import run_healthcheck

    return await run_healthcheck()


@router.get("/edge/cache/stats", summary="Stats del edge cache (HIT/MISS)")
async def platform_edge_cache_stats(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.edge.multiregion import cache_stats

    return await cache_stats()

# ------------------------------------------------------------------ PROMPT 29
# Cost Governance & FinOps v2

@router.get("/cost-governance/tags", summary="Tags de costo por org")
async def platform_cost_tags(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.costgov.cost_governance import list_tags

    return await list_tags(_parse_org(organization_id) if organization_id else None)


@router.post("/cost-governance/tags", status_code=201, summary="Crear tag de costo")
async def platform_cost_tag_create(body: CostTagIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import create_tag

    oid = _parse_org(body.organization_id)
    return await create_tag(oid, body.key, body.value)


@router.delete("/cost-governance/tags/{tag_id}", summary="Eliminar tag")
async def platform_cost_tag_delete(tag_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import delete_tag

    ok = await delete_tag(UUID(tag_id))
    if not ok:
        raise HTTPException(404, "Tag not found")
    return {"status": "deleted"}


@router.get("/cost-governance/costs", summary="Costos por tag (desglose)")
async def platform_cost_costs(
    request: Request, key: str, organization_id: str | None = None, days: int = 30
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.costgov.cost_governance import costs_by_tag

    return await costs_by_tag(
        _parse_org(organization_id) if organization_id else None, key, days
    )


@router.get("/cost-governance/showback", summary="Showback/chargeback por equipo")
async def platform_cost_showback(request: Request, organization_id: str | None = None, days: int = 30):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.costgov.cost_governance import showback

    return await showback(_parse_org(organization_id) if organization_id else None, days)


@router.get("/cost-governance/forecast", summary="Forecast de costos por modelo/plan")
async def platform_cost_forecast(request: Request, organization_id: str | None = None, days: int = 30):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.costgov.cost_governance import forecast

    return await forecast(_parse_org(organization_id) if organization_id else None, days)


@router.get("/cost-governance/alerts", summary="Alertas de costo disparadas")
async def platform_cost_alerts(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.costgov.cost_governance import list_alerts

    return await list_alerts(_parse_org(organization_id) if organization_id else None)


@router.post("/cost-governance/alerts/run", summary="Evaluar alertas ahora")
async def platform_cost_alerts_run(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import run_cost_alerts

    return await run_cost_alerts(_parse_org(organization_id) if organization_id else None)


@router.get("/cost-governance/alerts/rules", summary="Reglas de alerta adaptativas")
async def platform_cost_alert_rules(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.costgov.cost_governance import list_alert_rules

    return await list_alert_rules(_parse_org(organization_id) if organization_id else None)


@router.post("/cost-governance/alerts/rules", status_code=201, summary="Crear regla de alerta")
async def platform_cost_alert_rule_create(body: CostAlertRuleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import create_alert_rule

    oid = _parse_org(body.organization_id)
    return await create_alert_rule(
        oid, body.category, body.dimension, body.threshold_pct, body.adaptive
    )


@router.delete("/cost-governance/alerts/rules/{rule_id}", summary="Eliminar regla")
async def platform_cost_alert_rule_delete(rule_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import delete_alert_rule

    ok = await delete_alert_rule(UUID(rule_id))
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"status": "deleted"}


@router.post("/cost-governance/organizations/{organization_id}/units", summary="Team/BU de un org")
async def platform_cost_org_units(organization_id: str, body: CostUnitsIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.costgov.cost_governance import update_org_units

    return await update_org_units(_parse_org(organization_id), body.team, body.business_unit)


class CostTagIn(BaseModel):
    organization_id: str
    key: str = Field(..., min_length=1, max_length=60)
    value: str = Field(..., min_length=1, max_length=120)


class CostAlertRuleIn(BaseModel):
    organization_id: str
    category: str = Field(default="total", max_length=40)
    dimension: str | None = Field(default=None, max_length=120)
    threshold_pct: float = Field(default=20.0, ge=0, le=1000)
    adaptive: bool = True


class CostUnitsIn(BaseModel):
    team: str | None = Field(default=None, max_length=120)
    business_unit: str | None = Field(default=None, max_length=120)

# ------------------------------------------------------------------ PROMPT 30
# AI Ops Runbook & Incident Management v2

@router.get("/ops/runbooks", summary="Runbooks disponibles")
async def platform_ops_runbooks(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.opscenter.runbooks import list_runbooks

    return await list_runbooks()


@router.post("/ops/runbooks", status_code=201, summary="Crear runbook")
async def platform_ops_runbook_create(body: RunbookIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import create_runbook

    return await create_runbook(
        body.trigger_type, body.trigger_match, body.title, body.description, body.steps
    )


@router.delete("/ops/runbooks/{runbook_id}", summary="Eliminar runbook")
async def platform_ops_runbook_delete(runbook_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import delete_runbook

    ok = await delete_runbook(UUID(runbook_id))
    if not ok:
        raise HTTPException(404, "Runbook not found")
    return {"status": "deleted"}


@router.get("/ops/incidents", summary="Incidentes (filtros status/org/hours)")
async def platform_ops_incidents(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    hours: int = 168,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.opscenter.runbooks import list_incidents

    return await list_incidents(
        _parse_org(organization_id) if organization_id else None,
        status,
        hours,
    )


@router.post("/ops/incidents", status_code=201, summary="Abrir incidente")
async def platform_ops_incident_open(body: IncidentIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import open_incident

    oid = _parse_org(body.organization_id)
    return await open_incident(
        oid,
        title=body.title,
        description=body.description,
        source=body.source,
        severity=body.severity,
        actor=str(ctx.user_id),
        auto_runbook=body.auto_runbook,
    )



@router.get("/ops/incidents/metrics", summary="MTTR/MTTD por severidad")
async def platform_ops_incident_metrics(request: Request, hours: int = 168):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.opscenter.runbooks import incident_metrics

    return await incident_metrics(hours)


@router.get("/ops/incidents/{incident_id}", summary="Detalle + timeline")
async def platform_ops_incident_detail(incident_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.opscenter.runbooks import incident_detail

    detail = await incident_detail(UUID(incident_id))
    if detail is None:
        raise HTTPException(404, "Incident not found")
    return detail


@router.post("/ops/incidents/{incident_id}/ack", summary="Reconocer incidente")
async def platform_ops_incident_ack(incident_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import ack_incident

    ok = await ack_incident(UUID(incident_id), actor=str(ctx.user_id))
    if not ok:
        raise HTTPException(404, "Incident not found or already resolved")
    return {"status": "acknowledged"}


@router.post("/ops/incidents/{incident_id}/resolve", summary="Resolver incidente")
async def platform_ops_incident_resolve(incident_id: str, request: Request, resolution: str | None = None):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import resolve_incident

    ok = await resolve_incident(UUID(incident_id), actor=str(ctx.user_id), resolution=resolution)
    if not ok:
        raise HTTPException(404, "Incident not found or already resolved")
    return {"status": "resolved"}




@router.post("/ops/escalations/check", summary="Evaluar escalamientos pendientes")
async def platform_ops_escalations_check(request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.opscenter.runbooks import check_escalations

    return await check_escalations()


class RunbookIn(BaseModel):
    trigger_type: str = Field(..., max_length=60)
    trigger_match: str = Field(default="*", max_length=120)
    title: str = Field(..., max_length=160)
    description: str | None = None
    steps: list = Field(default_factory=list)


class IncidentIn(BaseModel):
    organization_id: str
    title: str = Field(..., max_length=200)
    description: str | None = None
    source: str = Field(default="manual", max_length=60)
    severity: str = Field(default="major", max_length=20)
    auto_runbook: bool = True

# ------------------------------------------------------------------ PROMPT 31
# AI Model Budgets & Guardrails v2

@router.get("/model-health/budgets", summary="Budgets por modelo (throttling)")
async def platform_model_budgets_status(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.modelhealth.guardrails import budgets_status

    return await budgets_status(_parse_org(organization_id) if organization_id else None)


@router.get("/model-health/guardrails", summary="Guardrails de salida por org")
async def platform_model_guardrails(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.modelhealth.guardrails import list_guardrails

    return await list_guardrails(_parse_org(organization_id) if organization_id else None)


@router.post("/model-health/guardrails", status_code=201, summary="Crear guardrail")
async def platform_model_guardrail_create(body: GuardrailIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.modelhealth.guardrails import create_guardrail

    oid = _parse_org(body.organization_id)
    try:
        return await create_guardrail(
            oid, body.name, body.kind, body.config, body.action
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/model-health/guardrails/{guardrail_id}", summary="Eliminar guardrail")
async def platform_model_guardrail_delete(guardrail_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.modelhealth.guardrails import delete_guardrail

    ok = await delete_guardrail(UUID(guardrail_id))
    if not ok:
        raise HTTPException(404, "Guardrail not found")
    return {"status": "deleted"}


@router.post("/model-health/guardrails/{guardrail_id}/toggle", summary="Activar/desactivar")
async def platform_model_guardrail_toggle(guardrail_id: str, body: GuardrailToggleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.modelhealth.guardrails import toggle_guardrail

    ok = await toggle_guardrail(UUID(guardrail_id), body.enabled)
    if not ok:
        raise HTTPException(404, "Guardrail not found")
    return {"status": "updated", "enabled": body.enabled}


@router.get("/model-health/circuits", summary="Circuit breakers por modelo")
async def platform_model_circuits(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.modelhealth.guardrails import circuits_list

    return await circuits_list()


@router.post("/model-health/circuits/{model}/trip", summary="Simular apertura del circuito")
async def platform_model_circuit_trip(model: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.modelhealth.guardrails import record_failure

    last = None
    for _ in range(5):
        last = await record_failure(model)
    return last


@router.post("/model-health/circuits/{model}/reset", summary="Resetear circuito")
async def platform_model_circuit_reset(model: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.modelhealth.guardrails import reset_circuit

    ok = await reset_circuit(model)
    if not ok:
        raise HTTPException(404, "Model not found")
    return {"status": "reset", "model": model}


@router.get("/model-health/dashboard", summary="Salud por modelo (tokens/errores/p95)")
async def platform_model_health_dashboard(request: Request, hours: int = 24):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.modelhealth.guardrails import model_health_dashboard

    return await model_health_dashboard(hours)


class GuardrailIn(BaseModel):
    organization_id: str
    name: str = Field(..., max_length=120)
    kind: str = Field(..., max_length=30)
    config: dict = Field(default_factory=dict)
    action: str = Field(default="mask", max_length=10)


class GuardrailToggleIn(BaseModel):
    enabled: bool = True

# ------------------------------------------------------------------ PROMPT 32
# Revenue Intelligence & ARR

@router.get("/revenue/summary", summary="ARR/MRR por plan + expansión/contracción")
async def platform_revenue_summary(request: Request, days: int = 30):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.revenue.revenue import revenue_summary

    return await revenue_summary(days)


@router.get("/revenue/funnels", summary="Cohortes trial→paid")
async def platform_revenue_funnels(request: Request, months: int = 12):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.revenue.revenue import conversion_funnels

    return await conversion_funnels(months)


@router.get("/revenue/forecast", summary="Forecast de revenue")
async def platform_revenue_forecast(request: Request, months: int = 6):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.revenue.revenue import revenue_forecast

    return await revenue_forecast(months)


@router.get("/revenue/events", summary="Ledger de eventos de suscripción")
async def platform_revenue_events(
    request: Request, organization_id: str | None = None, days: int = 30
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.revenue.revenue import list_events

    return await list_events(
        _parse_org(organization_id) if organization_id else None, days
    )


@router.get("/revenue/export.csv", summary="Export CSV por org/plan")
async def platform_revenue_export_csv(request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.revenue.revenue import export_revenue_csv

    csv_content = await export_revenue_csv()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="zent-revenue.csv"'
        },
    )

# ------------------------------------------------------------------ PROMPT 33
# Data Export & Compliance v2

@router.post("/data-export/export", status_code=201, summary="Export ZIP del tenant")
async def platform_data_export(body: DataExportIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.datacompliance.data_export import export_tenant

    oid = _parse_org(body.organization_id)
    return await export_tenant(
        oid,
        scope=body.scope,
        anonymized=body.anonymized,
        requested_by=ctx.user_id,
    )


@router.get("/data-export/exports", summary="Historial de exportaciones (auditoría)")
async def platform_data_exports(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.datacompliance.data_export import list_exports

    return await list_exports(_parse_org(organization_id) if organization_id else None)


@router.get("/data-export/exports/{export_id}/download", summary="Descargar ZIP")
async def platform_data_export_download(export_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.datacompliance.data_export import get_export_file

    content = await get_export_file(UUID(export_id))
    if content is None:
        raise HTTPException(404, "Export not found or expired")
    payload, scope = content
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="zent-export-{export_id[:8]}-{scope}.zip"'
        },
    )


@router.get("/data-export/retention/policies", summary="Políticas de retención")
async def platform_retention_policies(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.datacompliance.data_export import list_policies

    return await list_policies(_parse_org(organization_id) if organization_id else None)


@router.post("/data-export/retention/policies", status_code=201, summary="Upsert política")
async def platform_retention_policy_upsert(body: RetentionPolicyIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.datacompliance.data_export import upsert_policy

    try:
        return await upsert_policy(
            body.data_type,
            body.retention_days,
            body.enabled,
            _parse_org(body.organization_id) if body.organization_id else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/data-export/retention/policies/{policy_id}", summary="Eliminar política")
async def platform_retention_policy_delete(policy_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.datacompliance.data_export import delete_policy

    ok = await delete_policy(UUID(policy_id))
    if not ok:
        raise HTTPException(404, "Policy not found")
    return {"status": "deleted"}


@router.post("/data-export/retention/purge", summary="Ejecutar purgas ahora")
async def platform_retention_purge(request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.datacompliance.data_export import run_retention_purges

    return await run_retention_purges()


@router.get("/data-export/retention/purges", summary="Historial de purgas")
async def platform_retention_purges(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.datacompliance.data_export import list_purges

    return await list_purges()


class DataExportIn(BaseModel):
    organization_id: str
    scope: str = Field(default="all", max_length=40)
    anonymized: bool = False


class RetentionPolicyIn(BaseModel):
    data_type: str = Field(..., max_length=60)
    retention_days: int = Field(..., ge=0, le=3650)
    enabled: bool = True
    organization_id: str | None = None

# ------------------------------------------------------------------ PROMPT 34
# AI Trust & Safety Center

@router.get("/trust/aup/terms", summary="Términos de la AUP (versiones)")
async def platform_trust_aup_terms(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.trustsafety.trust_safety import get_terms

    return await get_terms()


@router.post("/trust/aup/accept", summary="Aceptar AUP por org")
async def platform_trust_aup_accept(body: AupAcceptIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import accept_terms

    oid = _parse_org(body.organization_id)
    return await accept_terms(oid, body.terms_version, ctx.user_id)


@router.get("/trust/aup/consents", summary="Consentimientos registrados")
async def platform_trust_aup_consents(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.trustsafety.trust_safety import list_consents

    return await list_consents()


@router.get("/trust/rules", summary="Reglas de moderación")
async def platform_trust_rules(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.trustsafety.trust_safety import list_moderation_rules

    return await list_moderation_rules(_parse_org(organization_id) if organization_id else None)


@router.post("/trust/rules", status_code=201, summary="Crear regla de moderación")
async def platform_trust_rule_create(body: ModerationRuleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import create_moderation_rule

    return await create_moderation_rule(
        body.name,
        body.category,
        body.patterns,
        body.min_score,
        body.action,
        _parse_org(body.organization_id) if body.organization_id else None,
    )


@router.post("/trust/rules/{rule_id}/toggle", summary="Activar/desactivar regla")
async def platform_trust_rule_toggle(rule_id: str, body: ModerationToggleIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import toggle_moderation_rule

    ok = await toggle_moderation_rule(UUID(rule_id), body.enabled)
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"status": "updated", "enabled": body.enabled}


@router.delete("/trust/rules/{rule_id}", summary="Eliminar regla")
async def platform_trust_rule_delete(rule_id: str, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import delete_moderation_rule

    ok = await delete_moderation_rule(UUID(rule_id))
    if not ok:
        raise HTTPException(404, "Rule not found")
    return {"status": "deleted"}


@router.get("/trust/incidents", summary="Incidentes de contenido")
async def platform_trust_incidents(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    direction: str | None = None,
    hours: int = 168,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.trustsafety.trust_safety import list_incidents

    return await list_incidents(
        _parse_org(organization_id) if organization_id else None,
        status,
        direction,
        hours,
    )


@router.post("/trust/incidents/{incident_id}/resolve", summary="Resolver incidente")
async def platform_trust_incident_resolve(incident_id: str, body: IncidentResolutionIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import resolve_incident

    ok = await resolve_incident(UUID(incident_id), body.note, ctx.user_id)
    if not ok:
        raise HTTPException(404, "Incident not found or not open")
    return {"status": "resolved"}


@router.post("/trust/incidents/{incident_id}/dismiss", summary="Desestimar incidente")
async def platform_trust_incident_dismiss(incident_id: str, body: IncidentResolutionIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.trustsafety.trust_safety import dismiss_incident

    ok = await dismiss_incident(UUID(incident_id), body.note)
    if not ok:
        raise HTTPException(404, "Incident not found or not open")
    return {"status": "dismissed"}


@router.get("/trust/dashboard", summary="Dashboard de confianza (tasas de bloqueo)")
async def platform_trust_dashboard(request: Request, hours: int = 24):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.trustsafety.trust_safety import trust_dashboard

    return await trust_dashboard(hours)


class AupAcceptIn(BaseModel):
    organization_id: str
    terms_version: int = Field(..., ge=1)


class ModerationRuleIn(BaseModel):
    name: str = Field(..., max_length=120)
    category: str = Field(default="prohibited_topics", max_length=40)
    patterns: list = Field(default_factory=list)
    min_score: float = Field(default=0.6, ge=0, le=1)
    action: str = Field(default="block", max_length=10)
    organization_id: str | None = None


class ModerationToggleIn(BaseModel):
    enabled: bool = True


class IncidentResolutionIn(BaseModel):
    note: str = Field(default="", max_length=500)

# ------------------------------------------------------------------ PROMPT 36
# AI Observability Traces & Spans v2

@router.get("/observability/traces", summary="Buscar trazas (filtros)")
async def platform_traces_list(
    request: Request,
    organization_id: str | None = None,
    agent_id: str | None = None,
    deployment_id: str | None = None,
    status: str | None = None,
    model: str | None = None,
    q: str | None = None,
    hours: int = 168,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.tracing.traces import list_traces

    return await list_traces(
        _parse_org(organization_id) if organization_id else None,
        agent_id=UUID(agent_id) if agent_id else None,
        deployment_id=UUID(deployment_id) if deployment_id else None,
        status=status,
        model=model,
        q=q,
        hours=hours,
    )



@router.get("/observability/traces/compare", summary="Comparar trazas side-by-side")
async def platform_traces_compare(request: Request, a: str, b: str):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.tracing.traces import compare_traces

    comparison = await compare_traces(a, b)
    if comparison is None:
        raise HTTPException(404, "One or both traces not found")
    return comparison


@router.get("/observability/traces/{trace_id}", summary="Detalle de traza con spans")
async def platform_trace_detail(trace_id: str, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.tracing.traces import get_trace

    trace = await get_trace(trace_id)
    if trace is None:
        raise HTTPException(404, "Trace not found")
    return trace




@router.get("/observability/traces/{trace_id}/usage", summary="Correlación con usage/billing")
async def platform_trace_usage(trace_id: str, request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.tracing.traces import trace_usage

    return await trace_usage(trace_id)


@router.get("/observability/stages", summary="Agregados por etapa")
async def platform_trace_stages(request: Request, hours: int = 24):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.tracing.traces import stages_dashboard

    return await stages_dashboard(hours)

# ------------------------------------------------------------------ PROMPT 37
# Multi-Tenant Notifications & Webhooks v2

@router.get("/notifications/deliveries", summary="Entregas de webhook (todas)")
async def platform_notifications_deliveries(
    request: Request,
    organization_id: str | None = None,
    status: str | None = None,
    hours: int = 168,
):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.notifyv2.notifications import list_deliveries

    return await list_deliveries(
        _parse_org(organization_id) if organization_id else None, status, hours
    )


@router.get("/notifications/deliveries/status", summary="Dashboard de entregas por suscripción")
async def platform_notifications_deliveries_status(request: Request, hours: int = 24):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.notifyv2.notifications import deliveries_dashboard

    return await deliveries_dashboard(hours)


@router.post("/notifications/trigger", summary="Enviar evento de prueba")
async def platform_notifications_trigger(body: NotificationTriggerIn, request: Request):
    ctx = require_platform_permission(request, "operations.write")
    from src.platform.notifyv2.notifications import notify

    oid = _parse_org(body.organization_id)
    return await notify(oid, body.event_type, body.title, body.body, body.data)


class NotificationTriggerIn(BaseModel):
    organization_id: str
    event_type: str = Field(..., max_length=60)
    title: str = Field(..., max_length=200)
    body: str | None = None
    data: dict = Field(default_factory=dict)

# ------------------------------------------------------------------ PROMPT 38
# Tenant Audit & Compliance Reports v2

@router.get("/compliance/dashboard", summary="Dashboard de cumplimiento por framework")
async def platform_compliance_dashboard(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.compliance.audit_reports import compliance_dashboard

    return await compliance_dashboard(
        _parse_org(organization_id) if organization_id else None
    )


@router.get("/compliance/controls", summary="Controles por framework")
async def platform_compliance_controls(request: Request, framework: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.compliance.audit_reports import list_controls

    return await list_controls(framework)


@router.get("/audit/reports", summary="Reportes de auditoría (todas las orgs)")
async def platform_audit_reports(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.compliance.audit_reports import list_reports

    return await list_reports(_parse_org(organization_id) if organization_id else None)

# ------------------------------------------------------------------ PROMPT 39
# Tenant Onboarding Experience v2

@router.get("/onboarding/metrics", summary="Métricas de activación (TTFV, tasa, funnel)")
async def platform_onboarding_metrics(request: Request):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.onboardingv2.onboarding import activation_metrics

    return await activation_metrics()


@router.get("/onboarding/status", summary="Progreso de onboarding por org")
async def platform_onboarding_status(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.onboardingv2.onboarding import status_by_org

    return await status_by_org()

# ------------------------------------------------------------------ PROMPT 40
# Sentiment & Feedback Analytics

@router.get("/feedback/analytics", summary="CSAT/NPS global por agente")
async def platform_feedback_analytics(
    request: Request,
    organization_id: str | None = None,
    agent_id: str | None = None,
    hours: int = 168,
):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.feedback.feedback import analytics

    return await analytics(
        _parse_org(organization_id) if organization_id else None,
        UUID(agent_id) if agent_id else None,
        hours,
    )


@router.get("/feedback/negative", summary="Causas del feedback negativo + correlación")
async def platform_feedback_negative(request: Request, organization_id: str | None = None, hours: int = 168):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.feedback.feedback import negative_breakdown

    return await negative_breakdown(
        _parse_org(organization_id) if organization_id else None, hours
    )


@router.get("/feedback/trends", summary="Tendencia diaria de feedback")
async def platform_feedback_trends(request: Request, organization_id: str | None = None, days: int = 14):
    ctx = require_platform_permission(request, "analytics.read")
    from src.platform.feedback.feedback import trends

    return await trends(_parse_org(organization_id) if organization_id else None, days)

# ------------------------------------------------------------------ PROMPT 41
# Tenant Data Migration Tools

@router.get("/migrations", summary="Migraciones de datos (todas)")
async def platform_migrations_list(request: Request, organization_id: str | None = None):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.migrate.migrations import list_migrations

    return await list_migrations(_parse_org(organization_id) if organization_id else None)


@router.get("/migrations/dashboard", summary="Resumen de migraciones por estado")
async def platform_migrations_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.migrate.migrations import list_migrations

    data = await list_migrations()
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for m in data["migrations"]:
        by_status[m["status"]] = by_status.get(m["status"], 0) + 1
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {
        "total": data["count"],
        "by_status": by_status,
        "by_kind": by_kind,
        "rows_applied_total": sum(m["rows_applied"] for m in data["migrations"]),
        "rows_failed_total": sum(m["rows_failed"] for m in data["migrations"]),
    }

# ------------------------------------------------------------------ PROMPT 42
# AI Agent Versioning & Rollout v2

@router.get("/releases/dashboard", summary="Dashboard de releases por agente")
async def platform_releases_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.releases.releases import releases_dashboard

    return await releases_dashboard()


@router.get("/releases", summary="Todas las releases")
async def platform_releases_list(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.releases.releases import list_releases

    return await list_releases()

# ------------------------------------------------------------------ PROMPT 43
# AI Copilot & Assistant Platform v2

@router.get("/copilot/dashboard", summary="Dashboard del copilot")
async def platform_copilot_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.copilot.copilot import copilot_dashboard

    return await copilot_dashboard()

# ------------------------------------------------------------------ PROMPT 44
# AI Workflow Automation Studio v2

@router.get("/workflows/dashboard", summary="Dashboard de workflows")
async def platform_workflows_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.workflows.engine import workflows_dashboard

    return await workflows_dashboard()

# ------------------------------------------------------------------ PROMPT 45
# AI Chat Analytics & Conversational Insights v2

@router.get("/chat-insights/dashboard", summary="Dashboard de insights conversacionales")
async def platform_chat_insights_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.chatinsights.insights import insights_dashboard

    return await insights_dashboard()

# ------------------------------------------------------------------ PROMPT 46
# AI Knowledge Hub v2

@router.get("/knowledge-hub/dashboard", summary="Dashboard del Knowledge Hub")
async def platform_knowledge_hub_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.knowledgehub.hub import knowledge_hub_dashboard

    return await knowledge_hub_dashboard()

# ------------------------------------------------------------------ PROMPT 47
# AI Risk & Compliance Center v2

@router.get("/risk-center/dashboard", summary="Dashboard de riesgos y cumplimiento")
async def platform_risk_center_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.riskcenter.risk_center import risk_compliance_dashboard

    return await risk_compliance_dashboard()

# ------------------------------------------------------------------ PROMPT 48
# AI Agent Marketplace & Ecosystem v2

@router.get("/ecosystem/dashboard", summary="Dashboard del ecosistema")
async def platform_ecosystem_dashboard(request: Request):
    ctx = require_platform_permission(request, "operations.read")
    from src.platform.marketplacev2.ecosystem import ecosystem_dashboard

    return await ecosystem_dashboard()

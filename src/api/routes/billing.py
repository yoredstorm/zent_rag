from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.billing_service import BillingService
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import PostgresBillingRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


def get_billing() -> BillingService:
    return BillingService(PostgresBillingRepository())


class CreateTrialRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    ruc: str | None = Field(default=None, max_length=50)


def _tenant_from_request(request: Request, x_tenant_id: str = "") -> UUID:
    """Resolve tenant from billing context (Bearer) or header fallback."""
    ctx = getattr(request.state, "billing_context", None)
    if ctx is not None:
        return ctx.tenant_id
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required or use Authorization Bearer")
    try:
        return UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id must be a valid UUID")


@router.get("/plans", summary="Listar planes disponibles")
async def list_plans(billing: BillingService = Depends(get_billing)):
    plans = await billing.get_plans()
    return {
        "plans": [
            {
                "id": str(p.id),
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "price_monthly_usd": p.price_monthly_cents / 100,
                "price_annual_usd": p.price_annual_cents / 100,
                "requests_per_month": p.requests_per_month,
                "max_tenants": p.max_tenants,
                "features": p.features,
                "is_trial": p.is_trial,
                "trial_days": p.trial_days,
            }
            for p in plans
        ]
    }


@router.get("/subscription", summary="Ver suscripcion actual")
async def get_subscription(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    billing: BillingService = Depends(get_billing),
):
    tenant_id = _tenant_from_request(request, x_tenant_id)

    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found for this tenant")

    used, month = await billing.get_quota_usage(sub.id)
    plan = None
    try:
        from src.infrastructure.relational_db import PostgresBillingRepository
        repo = PostgresBillingRepository()
        plan = await repo.get_plan_by_id(sub.plan_id)
    except Exception:
        pass

    return {
        "subscription_id": str(sub.id),
        "tenant_id": str(sub.tenant_id),
        "plan_id": str(sub.plan_id),
        "plan_name": plan.name if plan else None,
        "status": sub.status.value,
        "billing_interval": sub.billing_interval.value,
        "trial_start": sub.trial_start.isoformat() if sub.trial_start else None,
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "auto_renew": sub.auto_renew,
        "requests_used": used,
        "quota_month": month,
        "requests_limit": plan.requests_per_month if plan else None,
    }


@router.post("/subscription/cancel", summary="Cancelar suscripcion")
async def cancel_subscription(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    billing: BillingService = Depends(get_billing),
):
    tenant_id = _tenant_from_request(request, x_tenant_id)

    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found")

    await billing.cancel_subscription(sub.id)
    return {"status": "canceled", "subscription_id": str(sub.id)}


@router.post("/subscription/create-trial", summary="Crear trial gratuito")
async def create_trial(
    body: CreateTrialRequest,
    billing: BillingService = Depends(get_billing),
):
    try:
        return await _do_create_trial(body, billing)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create-trial failed", error=str(exc), exc_info=True)
        raise HTTPException(500, "Trial creation failed")


async def _do_create_trial(
    body: CreateTrialRequest,
    billing: BillingService,
):
    import hashlib

    from src.infrastructure.relational_db import PostgresTenantRepository, PostgresUserRepository

    tenant_id = uuid4()
    tenant_name = body.company_name.strip()
    tenant_id_str = str(tenant_id)

    tenant_repo = PostgresTenantRepository()
    api_key_hash = hashlib.sha256(f"auto-{tenant_id_str}".encode()).hexdigest()
    await tenant_repo.create_tenant(tenant_id, tenant_name, api_key_hash)

    profile = {
        "company_name": tenant_name,
        "email": body.email,
        "phone": body.phone,
        "country": body.country,
        "ruc": body.ruc,
    }
    profile = {k: v for k, v in profile.items() if v}
    if profile:
        await tenant_repo.update_tenant(tenant_id, **profile)

    logger.info("Created tenant for trial", tenant_id=tenant_id_str, name=tenant_name)

    user_repo = PostgresUserRepository()
    email_hash = hashlib.sha256(body.email.encode()).hexdigest()
    await user_repo.create_default_user(tenant_id, email_hash)
    logger.info("Auto-created default user", tenant_id=tenant_id_str)

    try:
        subscription, token = await billing.create_trial_subscription(tenant_id)
    except ValueError as exc:
        logger.error("No trial plan configured", error=str(exc))
        raise HTTPException(500, "No trial plan configured")
    except Exception as exc:
        logger.error("Failed to create trial subscription", error=str(exc), exc_info=True)
        raise HTTPException(500, "Failed to create trial")

    return {
        "subscription_id": str(subscription.id),
        "tenant_id": str(tenant_id),
        "company_name": tenant_name,
        "status": "trialing",
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "api_token": token,
        "message": "Free trial activated. Use the API token in Authorization: Bearer header.",
    }


@router.get("/token", summary="Info del token actual")
async def get_token(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    tenant_id = _tenant_from_request(request, x_tenant_id)

    billing = get_billing()
    subscription = await billing.get_subscription(tenant_id)
    if subscription is None:
        raise HTTPException(404, "No active subscription. Create a trial first.")

    token_info = await billing.get_token_info(subscription.id)
    if token_info is None:
        raise HTTPException(404, "No token found. Regenerate with POST /token/rotate.")

    return token_info


@router.post("/token/rotate", summary="Rotar token")
async def rotate_token(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    tenant_id = _tenant_from_request(request, x_tenant_id)

    billing = get_billing()
    subscription = await billing.get_subscription(tenant_id)
    if subscription is None:
        raise HTTPException(404, "No active subscription. Create a trial first.")

    token = await billing.rotate_token(subscription.id)
    return {
        "token": token,
        "message": "New token generated. Previous token is now invalid. Save this — it won't be shown again.",
    }


@router.get("/usage", summary="Uso del tenant (requests, tokens, historial)")
async def get_usage(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    days: int = 30,
    limit: int = 50,
):
    """Agregados desde usage_logs para el dashboard del portal."""
    from sqlalchemy import text

    from src.infrastructure.relational_db import get_async_session

    tenant_id = _tenant_from_request(request, x_tenant_id)
    days = max(1, min(days, 90))
    limit = max(1, min(limit, 200))

    session = await get_async_session()
    try:
        daily = await session.execute(
            text(
                """
                SELECT date_trunc('day', created_at)::date AS day,
                       COUNT(*)::int AS requests,
                       COALESCE(SUM(total_tokens), 0)::int AS tokens,
                       COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms
                FROM usage_logs
                WHERE tenant_id = :tid
                  AND created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY 1 DESC
                """
            ),
            {"tid": tenant_id, "days": str(days)},
        )
        recent = await session.execute(
            text(
                """
                SELECT id, total_tokens, latency_ms, model, created_at
                FROM usage_logs
                WHERE tenant_id = :tid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"tid": tenant_id, "lim": limit},
        )
        totals = await session.execute(
            text(
                """
                SELECT COUNT(*)::int AS requests,
                       COALESCE(SUM(total_tokens), 0)::int AS tokens,
                       COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms
                FROM usage_logs
                WHERE tenant_id = :tid
                  AND created_at >= NOW() - (:days || ' days')::interval
                """
            ),
            {"tid": tenant_id, "days": str(days)},
        )
        total_row = totals.fetchone()
        return {
            "tenant_id": str(tenant_id),
            "days": days,
            "totals": {
                "requests": total_row.requests if total_row else 0,
                "tokens": total_row.tokens if total_row else 0,
                "avg_latency_ms": round(total_row.avg_latency_ms, 2) if total_row else 0,
            },
            "daily": [
                {
                    "day": r.day.isoformat(),
                    "requests": r.requests,
                    "tokens": r.tokens,
                    "avg_latency_ms": round(r.avg_latency_ms, 2),
                }
                for r in daily.fetchall()
            ],
            "recent": [
                {
                    "id": r.id,
                    "total_tokens": r.total_tokens,
                    "latency_ms": r.latency_ms,
                    "model": r.model,
                    "created_at": r.created_at.isoformat(),
                }
                for r in recent.fetchall()
            ],
        }
    finally:
        await session.close()


@router.get("/admin/subscriptions", summary="Listar todas las suscripciones (admin)")
async def list_subscriptions(
    request: Request,
    billing: BillingService = Depends(get_billing),
):
    _require_admin_billing(request)
    subs = await billing.list_all_subscriptions()
    return {"subscriptions": subs, "total": len(subs)}


@router.post("/subscription/upgrade", summary="Cambiar de plan")
async def upgrade_plan(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    new_plan_name: str = Header(default="", alias="X-New-Plan"),
    billing_interval: str = Header(default="monthly", alias="X-Billing-Interval"),
    billing: BillingService = Depends(get_billing),
):
    from src.config import get_settings

    # Anti fraude: el upgrade a planes pagos exige flujo de pago. Sin
    # proveedor de pagos verificado, el self-service queda deshabilitado.
    if not get_settings().SELF_SERVICE_UPGRADE_ENABLED:
        raise HTTPException(
            403,
            "Plan upgrades require a verified payment flow. Contact support.",
        )

    tenant_id = _tenant_from_request(request, x_tenant_id)
    if not new_plan_name:
        raise HTTPException(400, "X-New-Plan required (plan name: starter, pro, enterprise)")

    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found. Create a trial first.")

    if billing_interval not in ("monthly", "annual"):
        billing_interval = "monthly"

    result = await billing.upgrade_plan(sub.id, new_plan_name, billing_interval)
    logger.info(
        "Plan upgraded",
        tenant_id=str(tenant_id),
        plan=result["plan_name"],
        interval=billing_interval,
    )
    return {
        "subscription_id": str(result["subscription_id"]),
        "plan": result["plan_name"],
        "billing_interval": result["billing_interval"],
        "message": f"Upgraded to {result['plan_name']} ({billing_interval}).",
    }


@router.delete("/admin/subscriptions/{subscription_id}", summary="Eliminar suscripcion (admin)")
async def delete_subscription(
    subscription_id: str,
    request: Request,
    billing: BillingService = Depends(get_billing),
):
    _require_admin_billing(request)
    await billing.delete_subscription(UUID(subscription_id))
    return {"status": "deleted", "subscription_id": subscription_id}


@router.put("/tenants/{tenant_id}", summary="Actualizar datos de empresa")
async def update_tenant(
    tenant_id: str,
    body: dict,
    request: Request,
):
    ctx_tid = _tenant_from_request(request)
    if str(ctx_tid) != tenant_id:
        raise HTTPException(403, "Cannot update another tenant")
    from src.infrastructure.relational_db import PostgresTenantRepository
    repo = PostgresTenantRepository()
    tenant = await repo.update_tenant(UUID(tenant_id), **body)
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "company_name": tenant.company_name,
        "ruc": tenant.ruc,
        "phone": tenant.phone,
        "email": tenant.email,
        "country": tenant.country,
        "status": tenant.status.value,
    }


@router.get("/admin/tenants", summary="Listar todos los tenants (admin)")
async def list_tenants(request: Request):
    _require_admin_billing(request)
    from src.infrastructure.relational_db import PostgresTenantRepository
    repo = PostgresTenantRepository()
    tenants = await repo.list_tenants()
    return {
        "tenants": [
            {
                "id": str(t.id),
                "name": t.name,
                "company_name": t.company_name,
                "ruc": t.ruc,
                "phone": t.phone,
                "email": t.email,
                "country": t.country,
                "status": t.status.value,
                "created_at": t.created_at.isoformat(),
            }
            for t in tenants
        ],
        "total": len(tenants),
    }


def _require_admin_billing(request: Request) -> None:
    from src.config import get_settings

    if not get_settings().RAG_ADMIN_ENABLED:
        raise HTTPException(403, "Admin billing endpoints disabled")

    # Admin de plataforma REAL: token con scope admin:*. Las sesiones del
    # portal (dueños de tenant) NO son admin de plataforma.
    from src.api.security import require_platform_admin

    require_platform_admin(request)

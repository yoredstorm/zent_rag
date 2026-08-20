from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.relational_db import (
    PostgresApiKeyRepository,
    PostgresBillingRepository,
    PostgresMembershipRepository,
    PostgresOrganizationRepository,
    PostgresUserRepository,
)
from src.platform.billing.service import BillingService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


def get_billing() -> BillingService:
    return BillingService(PostgresBillingRepository(), PostgresApiKeyRepository())


class CreateTrialRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=5, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    ruc: str | None = Field(default=None, max_length=50)


def _organization_from_request(request: Request, x_organization_id: str = "") -> UUID:
    """Resuelve la organización SOLO desde la identidad autenticada."""
    from src.api.security import resolve_organization

    return resolve_organization(request, x_organization_id, require_auth=False)


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
                "max_organizations": p.max_organizations,
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
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    billing: BillingService = Depends(get_billing),
):
    organization_id = _organization_from_request(request, x_organization_id)

    sub = await billing.get_subscription(organization_id)
    if sub is None:
        raise HTTPException(404, "No subscription found for this organization")

    used, month = await billing.get_quota_usage(sub.id)
    plan = None
    try:
        repo = PostgresBillingRepository()
        plan = await repo.get_plan_by_id(sub.plan_id)
    except Exception:
        pass

    return {
        "subscription_id": str(sub.id),
        "organization_id": str(sub.organization_id),
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
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    billing: BillingService = Depends(get_billing),
):
    from src.api.security import require_organization_admin

    require_organization_admin(request)
    organization_id = _organization_from_request(request, x_organization_id)

    sub = await billing.get_subscription(organization_id)
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

    organization_id = uuid4()
    organization_name = body.company_name.strip()

    organization_repo = PostgresOrganizationRepository()
    await organization_repo.create_organization(organization_id, organization_name)

    profile = {
        "company_name": organization_name,
        "email": body.email,
        "phone": body.phone,
        "country": body.country,
        "ruc": body.ruc,
    }
    profile = {k: v for k, v in profile.items() if v}
    if profile:
        await organization_repo.update_organization(organization_id, **profile)

    logger.info(
        "Created organization for trial",
        organization_id=str(organization_id),
        name=organization_name,
    )

    user_repo = PostgresUserRepository()
    email_hash = hashlib.sha256(body.email.encode()).hexdigest()
    user = await user_repo.create_default_user(organization_id, email_hash)
    membership_repo = PostgresMembershipRepository()
    await membership_repo.assign_role(organization_id, user.id, "owner")
    logger.info("Auto-created default user", organization_id=str(organization_id))

    try:
        subscription, token = await billing.create_trial_subscription(organization_id)
    except ValueError as exc:
        logger.error("No trial plan configured", error=str(exc))
        raise HTTPException(500, "No trial plan configured")
    except Exception as exc:
        logger.error("Failed to create trial subscription", error=str(exc), exc_info=True)
        raise HTTPException(500, "Failed to create trial")

    return {
        "subscription_id": str(subscription.id),
        "organization_id": str(organization_id),
        "company_name": organization_name,
        "status": "trialing",
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "api_token": token,
        "message": "Free trial activated. Use the API token in Authorization: Bearer header.",
    }


@router.get("/token", summary="Info de las API keys de la organización")
async def get_token(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    organization_id = _organization_from_request(request, x_organization_id)

    billing = get_billing()
    keys = await billing.list_api_keys(organization_id)
    return {"keys": keys, "count": len(keys)}


@router.post("/token/rotate", summary="Rotar token (revoca los activos y crea uno nuevo)")
async def rotate_token(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import require_organization_admin

    ctx = require_organization_admin(request)
    organization_id = _organization_from_request(request, x_organization_id)

    billing = get_billing()
    subscription = await billing.get_subscription(organization_id)
    if subscription is None:
        raise HTTPException(404, "No active subscription. Create a trial first.")

    # Revocar keys activas existentes y crear una nueva
    for key in await billing.list_api_keys(organization_id):
        if key["is_active"]:
            await billing.revoke_api_key(organization_id, UUID(key["id"]))

    token = await billing.create_api_key(
        organization_id, "Default", ["rag:query", "rag:ingest"], created_by=ctx.user_id
    )
    return {
        "token": token,
        "message": "New token generated. Previous tokens are now invalid. Save this — it won't be shown again.",
    }


@router.get("/usage", summary="Uso de la organización (requests, tokens, historial)")
async def get_usage(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    days: int = 30,
    limit: int = 50,
):
    """Agregados desde usage_logs para el dashboard del portal."""
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import get_async_session

    organization_id = _organization_from_request(request, x_organization_id)
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
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                GROUP BY 1
                ORDER BY 1 DESC
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        recent = await session.execute(
            text(
                """
                SELECT id, total_tokens, latency_ms, model, created_at
                FROM usage_logs
                WHERE organization_id = :oid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"oid": organization_id, "lim": limit},
        )
        totals = await session.execute(
            text(
                """
                SELECT COUNT(*)::int AS requests,
                       COALESCE(SUM(total_tokens), 0)::int AS tokens,
                       COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms
                FROM usage_logs
                WHERE organization_id = :oid
                  AND created_at >= NOW() - (:days || ' days')::interval
                """
            ),
            {"oid": organization_id, "days": str(days)},
        )
        total_row = totals.fetchone()
        return {
            "organization_id": str(organization_id),
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
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    new_plan_name: str = Header(default="", alias="X-New-Plan"),
    billing_interval: str = Header(default="monthly", alias="X-Billing-Interval"),
    billing: BillingService = Depends(get_billing),
):
    from src.api.security import require_organization_admin
    from src.core.config import get_settings

    # Anti fraude: el upgrade a planes pagos exige flujo de pago. Sin
    # proveedor de pagos verificado, el self-service queda deshabilitado.
    if not get_settings().SELF_SERVICE_UPGRADE_ENABLED:
        raise HTTPException(
            403,
            "Plan upgrades require a verified payment flow. Contact support.",
        )

    require_organization_admin(request)
    organization_id = _organization_from_request(request, x_organization_id)
    if not new_plan_name:
        raise HTTPException(400, "X-New-Plan required (plan name: starter, pro, enterprise)")

    sub = await billing.get_subscription(organization_id)
    if sub is None:
        raise HTTPException(404, "No subscription found. Create a trial first.")

    if billing_interval not in ("monthly", "annual"):
        billing_interval = "monthly"

    result = await billing.upgrade_plan(sub.id, new_plan_name, billing_interval)
    logger.info(
        "Plan upgraded",
        organization_id=str(organization_id),
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


@router.put("/organizations/{organization_id}", summary="Actualizar datos de empresa")
async def update_organization(
    organization_id: str,
    body: dict,
    request: Request,
):
    from src.api.security import require_organization_admin

    ctx = require_organization_admin(request)
    if str(ctx.organization_id) != organization_id:
        raise HTTPException(403, "Cannot update another organization")

    repo = PostgresOrganizationRepository()
    organization = await repo.update_organization(UUID(organization_id), **body)
    return {
        "id": str(organization.id),
        "name": organization.name,
        "company_name": organization.company_name,
        "ruc": organization.ruc,
        "phone": organization.phone,
        "email": organization.email,
        "country": organization.country,
        "status": organization.status.value,
    }


@router.get("/admin/organizations", summary="Listar todas las organizaciones (admin)")
async def list_organizations(request: Request):
    _require_admin_billing(request)
    repo = PostgresOrganizationRepository()
    organizations = await repo.list_organizations()
    return {
        "organizations": [
            {
                "id": str(o.id),
                "name": o.name,
                "company_name": o.company_name,
                "ruc": o.ruc,
                "phone": o.phone,
                "email": o.email,
                "country": o.country,
                "status": o.status.value,
                "created_at": o.created_at.isoformat(),
            }
            for o in organizations
        ],
        "total": len(organizations),
    }


def _require_admin_billing(request: Request) -> None:
    from src.core.config import get_settings

    if not get_settings().RAG_ADMIN_ENABLED:
        raise HTTPException(403, "Admin billing endpoints disabled")

    # Admin de plataforma REAL: token con scope admin:*. Las sesiones del
    # portal (dueños de organización) NO son admin de plataforma.
    from src.api.security import require_platform_admin

    require_platform_admin(request)

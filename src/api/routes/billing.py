from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from src.infrastructure.billing_service import BillingService
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import PostgresBillingRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


def get_billing() -> BillingService:
    return BillingService(PostgresBillingRepository())


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
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")
    tenant_id = UUID(tenant_id_str)

    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found for this tenant")

    used, month = await billing.get_quota_usage(sub.id)
    return {
        "subscription_id": str(sub.id),
        "tenant_id": str(sub.tenant_id),
        "plan_id": str(sub.plan_id),
        "status": sub.status.value,
        "billing_interval": sub.billing_interval.value,
        "trial_start": sub.trial_start.isoformat() if sub.trial_start else None,
        "trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
        "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "auto_renew": sub.auto_renew,
        "requests_used": used,
        "quota_month": month,
    }


@router.post("/subscription/cancel", summary="Cancelar suscripcion")
async def cancel_subscription(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    billing: BillingService = Depends(get_billing),
):
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")
    tenant_id = UUID(tenant_id_str)

    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found")

    await billing.cancel_subscription(sub.id)
    return {"status": "canceled", "subscription_id": str(sub.id)}


@router.post("/subscription/create-trial", summary="Crear trial gratuito")
async def create_trial(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    x_tenant_name: str = Header(default="", alias="X-Tenant-Name"),
    billing: BillingService = Depends(get_billing),
):
    try:
        return await _do_create_trial(request, x_tenant_id, x_tenant_name, billing)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create-trial failed", error=str(exc), exc_info=True)
        raise HTTPException(500, f"Trial creation failed: {type(exc).__name__}: {exc}")


async def _do_create_trial(
    request: Request,
    x_tenant_id: str,
    x_tenant_name: str,
    billing: BillingService,
):
    from src.infrastructure.relational_db import PostgresTenantRepository

    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")

    tenant_id = UUID(tenant_id_str)
    tenant_name = x_tenant_name or f"Tenant-{tenant_id_str[:8]}"

    tenant_repo = PostgresTenantRepository()
    tenant = await tenant_repo.get_by_id(tenant_id)
    if tenant is None:
        import hashlib
        api_key_hash = hashlib.sha256(f"auto-{tenant_id_str}".encode()).hexdigest()
        await tenant_repo.create_tenant(tenant_id, tenant_name, api_key_hash)
        logger.info("Auto-created tenant for trial", tenant_id=str(tenant_id))

    from src.infrastructure.relational_db import PostgresUserRepository
    user_repo = PostgresUserRepository()
    default_user = await user_repo.get_by_id(tenant_id, tenant_id)
    if default_user is None:
        import hashlib as _hl
        email_hash = _hl.sha256(f"default@{tenant_id_str}".encode()).hexdigest()
        await user_repo.create_default_user(tenant_id, email_hash)
        logger.info("Auto-created default user", tenant_id=str(tenant_id))

    existing = await billing.get_subscription(tenant_id)
    if existing is not None:
        raise HTTPException(409, "Tenant already has a subscription")

    try:
        subscription, token = await billing.create_trial_subscription(tenant_id)
    except ValueError as exc:
        raise HTTPException(500, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Failed to create trial: {exc}")

    return {
        "subscription_id": str(subscription.id),
        "tenant_id": str(tenant_id),
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
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")

    billing = get_billing()
    subscription = await billing.get_subscription(UUID(tenant_id_str))
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
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")

    billing = get_billing()
    subscription = await billing.get_subscription(UUID(tenant_id_str))
    if subscription is None:
        raise HTTPException(404, "No active subscription. Create a trial first.")

    token = await billing.rotate_token(subscription.id)
    return {
        "token": token,
        "message": "New token generated. Previous token is now invalid. Save this — it won't be shown again.",
    }


@router.get("/admin/subscriptions", summary="Listar todas las suscripciones (admin)")
async def list_subscriptions(billing: BillingService = Depends(get_billing)):
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
    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(400, "X-Tenant-Id required")
    if not new_plan_name:
        raise HTTPException(400, "X-New-Plan required (plan name: starter, pro, enterprise)")

    tenant_id = UUID(tenant_id_str)
    sub = await billing.get_subscription(tenant_id)
    if sub is None:
        raise HTTPException(404, "No subscription found. Create a trial first.")

    if billing_interval not in ("monthly", "annual"):
        billing_interval = "monthly"

    result = await billing.upgrade_plan(sub.id, new_plan_name, billing_interval)
    return {
        "subscription_id": str(result["subscription_id"]),
        "plan": result["plan_name"],
        "billing_interval": result["billing_interval"],
        "message": f"Upgraded to {result['plan_name']} ({billing_interval}).",
    }


@router.delete("/admin/subscriptions/{subscription_id}", summary="Eliminar suscripcion (admin)")
async def delete_subscription(
    subscription_id: str,
    billing: BillingService = Depends(get_billing),
):
    await billing.delete_subscription(UUID(subscription_id))
    return {"status": "deleted", "subscription_id": subscription_id}


@router.put("/tenants/{tenant_id}", summary="Actualizar datos de empresa")
async def update_tenant(
    tenant_id: str,
    body: dict,
):
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
async def list_tenants():
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

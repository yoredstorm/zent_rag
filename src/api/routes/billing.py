from __future__ import annotations

import json
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

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


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_name: str = Field(..., min_length=1, max_length=100)
    interval: Literal["monthly", "annual"] = "monthly"


def _organization_from_request(request: Request, x_organization_id: str = "") -> UUID:
    """Resuelve la organización SOLO desde la identidad autenticada."""
    from src.api.security import resolve_organization

    return resolve_organization(request, x_organization_id, require_auth=False)


@router.get("/plans", summary="Listar planes disponibles")
async def list_plans(billing: BillingService = Depends(get_billing)):
    plans = await billing.get_plans()
    from src.platform.billing.entitlements import get_entitlements_for_plans

    ents = await get_entitlements_for_plans([p.id for p in plans])
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
                "entitlements": ents.get(p.id, {}),
                "is_trial": p.is_trial,
                "trial_days": p.trial_days,
            }
            for p in plans
        ]
    }


@router.get("/entitlements", summary="Entitlements del plan de la organización")
async def get_entitlements(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.platform.billing.entitlements import get_org_entitlements
    from src.platform.rbac.policy import require_permission

    require_permission(request, "billing:read")
    organization_id = _organization_from_request(request, x_organization_id)
    return await get_org_entitlements(organization_id)


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

    from sqlalchemy import text

    from src.core.config import get_settings
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()
    payment_provider = "manual"
    provider_subscription_id = None
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT payment_provider, provider_subscription_id "
                    "FROM subscriptions WHERE id = :sid"
                ),
                {"sid": sub.id},
            )
        ).fetchone()
        if row is not None:
            payment_provider = str(row.payment_provider or "manual")
            provider_subscription_id = row.provider_subscription_id
    finally:
        await session.close()

    settings = get_settings()
    checkout_available = (
        settings.SELF_SERVICE_UPGRADE_ENABLED
        and settings.PAYMENT_PROVIDER.strip().lower() == "stripe"
    )

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
        "payment_provider": payment_provider,
        "provider_subscription_id": provider_subscription_id,
        "self_service_upgrade_enabled": settings.SELF_SERVICE_UPGRADE_ENABLED,
        "checkout_available": checkout_available,
    }


@router.post("/subscription/cancel", summary="Cancelar suscripcion")
async def cancel_subscription(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    billing: BillingService = Depends(get_billing),
):
    from src.api.security import require_organization_admin
    from src.platform.rbac.policy import require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
    organization_id = _organization_from_request(request, x_organization_id)

    sub = await billing.get_subscription(organization_id)
    if sub is None:
        raise HTTPException(404, "No subscription found")

    from sqlalchemy import text

    from src.infrastructure.billing.provider import get_payment_provider
    from src.infrastructure.postgres.session import get_async_session
    from src.platform.billing.invoices import ensure_billing_tables

    await ensure_billing_tables()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT provider_subscription_id FROM subscriptions WHERE id = :sid"
                ),
                {"sid": sub.id},
            )
        ).fetchone()
        provider_sub_id = row.provider_subscription_id if row else None
    finally:
        await session.close()
    try:
        await get_payment_provider().cancel_subscription(
            organization_id, provider_sub_id
        )
    except Exception:
        logger.warning("Provider cancel failed; continuing with local cancel")

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
    from src.platform.rbac.policy import require_permission

    ctx = require_organization_admin(request)
    require_permission(request, "billing:write")
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
        organization_id, "Default", ["rag:read", "rag:write"], created_by=ctx.user_id
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
    from src.platform.rbac.policy import require_permission
    from src.platform.usage.aggregation import get_organization_usage

    require_permission(request, "billing:read")

    organization_id = _organization_from_request(request, x_organization_id)
    return await get_organization_usage(organization_id, days=days, limit=limit)


@router.get("/admin/subscriptions", summary="Listar todas las suscripciones (admin)")
async def list_subscriptions(
    request: Request,
    billing: BillingService = Depends(get_billing),
):
    _require_admin_billing(request)
    subs = await billing.list_all_subscriptions()
    return {"subscriptions": subs, "total": len(subs)}


@router.post("/checkout", status_code=201, summary="Crear sesión de Stripe Checkout")
async def create_checkout(
    body: CheckoutRequest,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import require_organization_admin
    from src.core.config import get_settings
    from src.infrastructure.billing.provider import get_payment_provider
    from src.platform.rbac.policy import require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
    settings = get_settings()
    if not settings.SELF_SERVICE_UPGRADE_ENABLED:
        raise HTTPException(
            403,
            "Plan upgrades require a verified payment flow. Contact support.",
        )
    if settings.PAYMENT_PROVIDER.strip().lower() != "stripe":
        raise HTTPException(
            409,
            "Stripe checkout requires PAYMENT_PROVIDER=stripe",
        )
    organization_id = _organization_from_request(request, x_organization_id)
    plan_name = body.plan_name.strip().lower()
    if plan_name in {"enterprise", "trial"}:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "plan_not_self_service",
                "message": "Enterprise and trial plans are not available via Checkout",
            },
        )
    plans = await get_billing().get_plans()
    target = next((p for p in plans if p.name == plan_name), None)
    if target is None or not target.is_public:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "plan_not_self_service",
                "message": "Plan is not available for self-service checkout",
            },
        )
    provider = get_payment_provider()
    try:
        session = await provider.create_checkout_session(
            organization_id, plan_name, body.interval
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    logger.info(
        "Stripe checkout session created",
        organization_id=str(organization_id),
        plan=plan_name,
    )
    return {
        "checkout_url": session.checkout_url,
        "session_id": session.session_id,
    }


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
    settings = get_settings()
    if not settings.SELF_SERVICE_UPGRADE_ENABLED:
        raise HTTPException(
            403,
            "Plan upgrades require a verified payment flow. Contact support.",
        )

    from src.platform.rbac.policy import require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
    organization_id = _organization_from_request(request, x_organization_id)
    if not new_plan_name:
        raise HTTPException(400, "X-New-Plan required (plan name: starter, pro, enterprise)")

    if settings.PAYMENT_PROVIDER.strip().lower() == "stripe":
        from src.infrastructure.billing.provider import get_payment_provider

        interval = billing_interval if billing_interval in ("monthly", "annual") else "monthly"
        if new_plan_name.strip().lower() in {"enterprise", "trial"}:
            raise HTTPException(
                status_code=409,
                detail={
                    "error_code": "plan_not_self_service",
                    "message": "Enterprise and trial plans are not available via Checkout",
                },
            )
        provider = get_payment_provider()
        try:
            session = await provider.create_checkout_session(
                organization_id, new_plan_name.strip().lower(), interval
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "checkout_url": session.checkout_url,
            "session_id": session.session_id,
            "message": "Complete payment in Stripe Checkout. The plan changes after the webhook.",
        }

    from src.platform.rbac.policy import require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
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
    from src.platform.rbac.policy import require_permission

    ctx = require_organization_admin(request)
    require_permission(request, "billing:write")
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


# -----------------------------------------------------------------------------
# Usage & Cost Engine — métricas por agent/api-key/storage + pricing + alerts
# -----------------------------------------------------------------------------
class PricingUpdateBody(BaseModel):
    provider: str = Field(..., min_length=1, max_length=60)
    model: str = Field(..., min_length=1, max_length=120)
    input_cost_per_1k: float = Field(..., ge=0.0, le=100.0)
    output_cost_per_1k: float = Field(..., ge=0.0, le=100.0)
    embedding_cost_per_1k: float = Field(default=0.0, ge=0.0, le=100.0)
    currency: str = Field(default="USD", max_length=3)


@router.get("/usage/agents", summary="Uso por agente (admin org)")
async def usage_by_agent(
    request: Request,
    days: int = 30,
):
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import get_async_session
    from src.platform.rbac.policy import require_permission

    require_permission(request, "billing:read")
    organization_id = _organization_from_request(request)
    days = max(1, min(days, 90))
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT agent_id, COUNT(*)::int AS requests, "
                    "COALESCE(SUM(total_tokens), 0)::int AS tokens, "
                    "COALESCE(SUM(estimated_cost), 0)::float AS cost, "
                    "COALESCE(AVG(latency_ms), 0)::float AS avg_latency_ms "
                    "FROM usage_events "
                    "WHERE organization_id = :oid AND agent_id IS NOT NULL "
                    "AND created_at >= NOW() - (:days || ' days')::interval "
                    "GROUP BY agent_id ORDER BY requests DESC"
                ),
                {"oid": organization_id, "days": str(days)},
            )
        ).fetchall()
        return {
            "agents": [
                {
                    "agent_id": str(r.agent_id),
                    "requests": r.requests,
                    "tokens": r.tokens,
                    "estimated_cost": round(r.cost, 8),
                    "avg_latency_ms": round(r.avg_latency_ms, 2),
                }
                for r in rows
            ]
        }
    finally:
        await session.close()


@router.get("/usage/api-keys", summary="Uso por API key (admin org)")
async def usage_by_api_key(
    request: Request,
    days: int = 30,
):
    from sqlalchemy import text

    from src.infrastructure.postgres.relational_db import get_async_session
    from src.platform.rbac.policy import require_permission

    require_permission(request, "billing:read")
    organization_id = _organization_from_request(request)
    days = max(1, min(days, 90))
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT api_key_id, COUNT(*)::int AS requests, "
                    "COALESCE(SUM(estimated_cost), 0)::float AS cost "
                    "FROM usage_events "
                    "WHERE organization_id = :oid AND api_key_id IS NOT NULL "
                    "AND created_at >= NOW() - (:days || ' days')::interval "
                    "GROUP BY api_key_id ORDER BY requests DESC"
                ),
                {"oid": organization_id, "days": str(days)},
            )
        ).fetchall()
        return {
            "api_keys": [
                {
                    "api_key_id": str(r.api_key_id),
                    "requests": r.requests,
                    "estimated_cost": round(r.cost, 8),
                }
                for r in rows
            ]
        }
    finally:
        await session.close()


@router.get("/usage/storage", summary="Storage vectorial del tenant")
async def usage_storage(request: Request):
    from src.platform.rbac.policy import require_permission

    require_permission(request, "billing:read")
    organization_id = _organization_from_request(request)
    from src.agents.tools.schema_relevance import SchemaCache  # noqa: F401
    from src.api.deps import get_cache_provider

    cache = get_cache_provider()
    key = f"usage:storage:{organization_id.hex}"
    cached = await cache.get(key)
    if cached is not None:
        return {"organization_id": str(organization_id), **json.loads(cached)}

    from qdrant_client import models as qdrant_models

    from src.infrastructure.qdrant.vector_store import (
        RAG_DOCUMENTS_COLLECTION,
        _get_client,
    )

    client = await _get_client()
    try:
        count = await client.count(
            collection_name=RAG_DOCUMENTS_COLLECTION,
            count_filter=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="organization_id",
                        match=qdrant_models.MatchValue(value=str(organization_id)),
                    )
                ]
            ),
            exact=True,
        )
        points = int(count.count or 0)
    except Exception as exc:
        points = 0
    payload = {"vector_points": points}
    await cache.set(key, json.dumps(payload), ttl_seconds=3600)
    return {"organization_id": str(organization_id), **payload}


@router.get("/pricing", summary="Precios del registry (admin org)")
async def get_pricing(request: Request):
    from src.platform.billing.pricing import list_prices
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    prices = await list_prices()
    return {"prices": prices, "count": len(prices)}


@router.put("/pricing", summary="Actualizar precio sin deploy (admin org)")
async def put_pricing(body: PricingUpdateBody, request: Request):
    from src.platform.billing.pricing import upsert_price
    from src.platform.rbac.policy import require_organization_admin, require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
    await upsert_price(
        provider=body.provider,
        model=body.model,
        input_cost_per_1k=body.input_cost_per_1k,
        output_cost_per_1k=body.output_cost_per_1k,
        embedding_cost_per_1k=body.embedding_cost_per_1k,
        currency=body.currency,
    )
    return {"status": "updated", "provider": body.provider, "model": body.model}


@router.get("/usage/alerts", summary="Alertas de quota (admin org)")
async def get_usage_alerts(request: Request, limit: int = 50):
    from src.platform.billing.alerts import list_alerts
    from src.platform.rbac.policy import require_permission

    require_permission(request, "billing:read")
    organization_id = _organization_from_request(request)
    alerts = await list_alerts(organization_id, limit=min(limit, 200))
    return {"alerts": alerts, "count": len(alerts)}


@router.post("/usage/alerts/{alert_id}/ack", summary="Reconocer alerta")
async def ack_usage_alert(alert_id: str, request: Request):
    from src.platform.billing.alerts import acknowledge_alert
    from src.platform.rbac.policy import require_organization_admin, require_permission

    require_organization_admin(request)
    require_permission(request, "billing:write")
    organization_id = _organization_from_request(request)
    try:
        aid = UUID(alert_id)
    except ValueError:
        raise HTTPException(400, "alert_id must be a valid UUID") from None
    ok = await acknowledge_alert(organization_id, aid)
    if not ok:
        raise HTTPException(404, "Alert not found or already acknowledged")
    return {"status": "acknowledged"}


@router.get("/reconciliation", summary="Reconciliar usage vs invoices vs payments (admin)")
async def billing_reconciliation(request: Request, days: int = 30):
    from src.platform.billing.reconciliation import reconcile
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = _organization_from_request(request)
    report = await reconcile(organization_id, days=days)
    return {"organization_id": str(organization_id), "report": report}


@router.get("/invoices", summary="Facturas de la organización")
async def list_org_invoices(request: Request, limit: int = 50):
    from src.platform.billing.invoices import list_invoices
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = _organization_from_request(request)
    invoices = await list_invoices(organization_id, limit=min(limit, 200))
    return {"invoices": invoices, "count": len(invoices)}


def _require_admin_billing(request: Request) -> None:
    from src.core.config import get_settings

    if not get_settings().RAG_ADMIN_ENABLED:
        raise HTTPException(403, "Admin billing endpoints disabled")

    # Admin de plataforma REAL: token con scope admin:*. Las sesiones del
    # portal (dueños de organización) NO son admin de plataforma.
    from src.api.security import require_platform_admin

    require_platform_admin(request)

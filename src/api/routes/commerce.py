# =============================================================================
# Commerce API — catálogo, órdenes, proveedores de pago, KPIs y webhooks
# =============================================================================
# Superficies:
#   tenant  /api/v1/commerce/*          (sesión + permisos de workflow)
#   público /api/v1/public/payments/*   (webhook de proveedor, firma obligatoria)
#
# Nada de aquí acepta montos del cliente: el precio sale del catálogo y el monto
# del checkout sale de la orden persistida.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger
from src.platform.commerce import contracts as C
from src.platform.commerce import sales_funnel, store
from src.platform.commerce.payments import service as payments
from src.platform.commerce.payments.base import PaymentProviderError
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/commerce", tags=["Commerce"])
public_router = APIRouter(prefix="/api/v1/public/payments", tags=["Payment Provider Webhook"])


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class ProductIn(BaseModel):
    sku: str = Field(..., max_length=64)
    name: str = Field(..., max_length=240)
    price: float = Field(..., ge=0)
    currency: str = Field(default="PEN", max_length=3)
    unit: str = Field(default="UNIT", max_length=16)
    description: str | None = Field(default=None, max_length=2000)
    aliases: list[str] = Field(default_factory=list)
    category: str | None = Field(default=None, max_length=80)
    stock: float | None = Field(default=None, ge=0)


class PaymentProviderIn(BaseModel):
    #: Credenciales del proveedor. NUNCA se devuelven ni se guardan en claro:
    #: van al SecretStore y el manifest solo guarda un `credential_ref`.
    secrets: dict[str, Any] = Field(default_factory=dict)
    mode: str = Field(default="test", max_length=16)
    config: dict[str, Any] = Field(default_factory=dict)
    display_name: str | None = Field(default=None, max_length=120)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
@router.get("/products", summary="Catálogo de productos del tenant")
async def list_products(request: Request, q: str | None = None, limit: int = 50):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    if q:
        result = await store.search_products(org, q, limit=limit)
        return {"products": result["products"], "count": result["count"], "summary": result["summary"]}
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    await store.ensure_commerce_tables()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM commerce_products WHERE organization_id = :oid AND active = TRUE "
                    "ORDER BY name LIMIT :lim"
                ),
                {"oid": str(org), "lim": max(1, min(int(limit), 200))},
            )
        ).fetchall()
    finally:
        await session.close()
    products = []
    for row in rows:
        product = await store.get_product(org, product_id=str(row.id))
        if product:
            products.append(product)
    return {"products": products, "count": len(products)}


@router.post("/products", summary="Crear o actualizar un producto del catálogo")
async def upsert_product(request: Request, body: ProductIn):
    org = UUID(str(require_permission(request, "workflows:run").organization_id))
    try:
        product = await store.upsert_product(
            org,
            sku=body.sku,
            name=body.name,
            price=body.price,
            currency=body.currency,
            unit=body.unit,
            description=body.description,
            aliases=body.aliases,
            category=body.category,
            stock=body.stock,
        )
    except store.CommerceError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    return {"product": product}


# ---------------------------------------------------------------------------
# Órdenes y ventas
# ---------------------------------------------------------------------------
@router.get("/orders", summary="Órdenes del tenant")
async def list_orders(request: Request, status: str | None = None, limit: int = 50):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    orders = await store.list_orders(org, status=status, limit=limit)
    return {"orders": orders, "count": len(orders)}


@router.get("/orders/{order_id}", summary="Detalle de una orden")
async def get_order(request: Request, order_id: str):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    order = await store.get_order(org, order_id=order_id)
    if order is None:
        raise HTTPException(404, "orden no encontrada")
    return {"order": order}


# ---------------------------------------------------------------------------
# Proveedores de pago (BYOC con SecretStore)
# ---------------------------------------------------------------------------
@router.get("/payments/providers", summary="Proveedores de pago configurados")
async def list_providers(request: Request):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    providers = await store.list_payment_providers(org)
    configured = {p["provider"] for p in providers if p["status"] == "connected"}
    return {
        "providers": providers,
        "available": [
            {
                "provider": name,
                "configured": name in configured,
                "required_credentials": list(C.PROVIDER_SECRET_KEYS.get(name, ())),
                "capabilities": list(C.PAYMENT_CAPABILITIES),
                "events": list(C.PAYMENT_EVENTS),
            }
            for name in C.PAYMENT_PROVIDERS
        ],
    }


@router.put("/payments/providers/{provider}", summary="Configurar credenciales de pago")
async def configure_provider(request: Request, provider: str, body: PaymentProviderIn):
    org = UUID(str(require_permission(request, "workflows:run").organization_id))
    try:
        record = await payments.configure_provider(
            org,
            provider=provider,
            secrets=body.secrets,
            mode=body.mode,
            config=body.config,
            display_name=body.display_name,
        )
    except PaymentProviderError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
    # Nunca se devuelven secretos: solo el hecho de que quedaron configurados.
    return {
        "provider": record["provider"],
        "status": record["status"],
        "mode": record["mode"],
        "credential_ref": record["credential_ref"],
        "capabilities": record["capabilities"],
        "events": record["events"],
    }


@router.get("/payments/events", summary="Eventos de proveedor recibidos (auditoría)")
async def list_provider_events(request: Request, limit: int = 50):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    events = await store.list_provider_events(org, limit=limit)
    return {"events": events, "count": len(events)}


# ---------------------------------------------------------------------------
# Readiness del embudo + KPIs
# ---------------------------------------------------------------------------
@router.get("/sales-funnel/readiness", summary="Checklist de configuración del embudo")
async def sales_funnel_readiness(request: Request):
    """Checklist ✓ / ! que la UI muestra sin errores técnicos."""
    from src.platform.workflows.bindings import resolve_binding
    from src.platform.workflows.event_registry import is_registered

    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    items: list[dict[str, Any]] = []
    for item in sales_funnel.readiness_items():
        resolved: list[str] = []
        missing: list[str] = []
        for capability in list(item.get("capabilities") or []):
            binding = await resolve_binding(org, capability)
            if binding is not None or item.get("builtin"):
                resolved.append(capability)
            else:
                missing.append(capability)
        for event_type in list(item.get("events") or []):
            if is_registered(event_type):
                resolved.append(event_type)
            else:
                missing.append(event_type)
        status = "ok" if not missing else "attention"
        items.append(
            {
                "key": item["key"],
                "label": item["label"],
                "status": status,
                "resolved": resolved,
                "missing": missing,
                "hint": item.get("hint"),
                "action": (
                    None
                    if status == "ok"
                    else {
                        "kind": "marketplace",
                        "filter": item.get("marketplace_filter") or "payments",
                        "label": "Configurar medio de pago",
                    }
                ),
            }
        )
    return {
        "title": "Configura tu embudo",
        "ready": all(i["status"] == "ok" for i in items),
        "items": items,
    }


@router.get("/kpis", summary="KPIs del embudo de ventas")
async def kpis(request: Request, workflow_id: str | None = None):
    org = UUID(str(require_permission(request, "workflows:read").organization_id))
    return await store.workflow_kpis(org, workflow_id=workflow_id)


# ---------------------------------------------------------------------------
# Webhook de proveedor (público, firma obligatoria)
# ---------------------------------------------------------------------------
@public_router.post("/{provider}/webhook", summary="Webhook del proveedor de pago")
async def payment_provider_webhook(provider: str, request: Request):
    """provider → firma → normalización → dedupe → BusinessEvent → señal.

    Un payload externo NUNCA se convierte en señal sin verificación de firma y
    sin resolver el tenant desde nuestro propio registro de checkouts.
    """
    raw_body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        result = await payments.ingest_provider_webhook(
            provider, raw_body=raw_body, headers=headers
        )
    except PaymentProviderError as exc:
        status_code = 400 if exc.code in ("SIGNATURE_INVALID", "PROVIDER_UNKNOWN") else 422
        logger.warning(
            "provider webhook rejected", provider=provider, code=exc.code, error=exc.message[:200]
        )
        raise HTTPException(status_code, {"code": exc.code, "message": exc.message}) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("provider webhook failed", provider=provider, error=str(exc)[:200])
        raise HTTPException(500, "webhook processing failed") from exc
    return result

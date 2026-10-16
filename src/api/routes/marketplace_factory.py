# =============================================================================
# Phase 33A — Marketplace Factory API (Control Center) + catálogo tenant
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Router de Control Center (factory con autoridad de plataforma).
cc_router = APIRouter(prefix="/api/v1/platform/marketplace", tags=["Marketplace Factory"])

# Router de catálogo para tenants.
tenant_router = APIRouter(prefix="/api/v1/products", tags=["Product Catalog"])


def _cc_require(request: Request, permission: str = "marketplace_factory:manage"):
    from src.platform.rbac.authorization import require_platform_permission

    return require_platform_permission(request, permission)


def _tenant_require(request: Request, permission: str):
    from src.platform.rbac.policy import require_permission

    return require_permission(request, permission)


async def _workspace_id(request: Request) -> UUID | None:
    from src.platform.workspaces.context import (
        get_active_workspace_id,
        workspace_header_or_none,
    )

    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        return None
    header = workspace_header_or_none(request)
    if header is not None:
        return header
    try:
        active = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
        if active is not None:
            return active
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# Control Center — Overview y paleta
# ---------------------------------------------------------------------------
@cc_router.get("/overview", summary="Overview de la factory")
async def factory_overview(request: Request):
    _cc_require(request)
    from src.platform.marketplace.factory import assets_palette
    from src.platform.marketplace.products import product_analytics

    analytics = await product_analytics()
    palette = await assets_palette()
    return {**analytics, "palette": palette}


@cc_router.post("/migrate-legacy", summary="Crear productos desde assets legacy")
async def factory_migrate_legacy(request: Request):
    ctx = _cc_require(request)
    from src.platform.marketplace.factory import migrate_legacy_to_products

    return await migrate_legacy_to_products(created_by=ctx.user_id)


@cc_router.post("/sync", summary="Sincronizar catálogo único desde assets técnicos")
async def factory_sync(request: Request):
    ctx = _cc_require(request)
    from src.platform.marketplace.factory import sync_catalog_from_assets

    return await sync_catalog_from_assets(created_by=ctx.user_id)


# ---------------------------------------------------------------------------
# Control Center — Products CRUD + pipeline
# ---------------------------------------------------------------------------
@cc_router.get("/products", summary="Lista de productos")
async def factory_products(
    request: Request,
    product_type: str | None = None,
    status: str | None = None,
):
    _cc_require(request)
    from src.platform.marketplace.products import list_products

    return await list_products(product_type=product_type, status=status, include_hidden=True)


@cc_router.post("/products", summary="Crear/actualizar producto (v1)", status_code=201)
async def factory_product_save(body: dict, request: Request):
    ctx = _cc_require(request)
    from src.platform.marketplace.products import ProductError, save_product

    try:
        return await save_product(body, created_by=ctx.user_id)
    except ProductError as exc:
        raise HTTPException(400, str(exc)) from exc


@cc_router.get("/products/{product_id}", summary="Detalle de producto")
async def factory_product_detail(product_id: str, request: Request):
    _cc_require(request)
    from src.platform.marketplace.products import get_product

    result = await get_product(product_id=UUID(product_id))
    if result is None:
        raise HTTPException(404, "Producto no encontrado")
    return result


@cc_router.post("/products/{product_id}/versions", summary="Nueva versión DRAFT (clon)")
async def factory_product_version(product_id: str, body: VersionIn, request: Request):
    ctx = _cc_require(request)
    from src.platform.marketplace.products import ProductError, set_version

    try:
        return await set_version(UUID(product_id), body.version, created_by=ctx.user_id)
    except ProductError as exc:
        raise HTTPException(400, str(exc)) from exc


@cc_router.post("/products/{product_id}/transition", summary="Cambiar estado (publish gate)")
async def factory_product_transition(product_id: str, body: TransitionIn, request: Request):
    _cc_require(request)
    from src.platform.marketplace.products import ProductError, transition

    try:
        return await transition(UUID(product_id), body.status)
    except ProductError as exc:
        raise HTTPException(400, str(exc)) from exc


@cc_router.post("/products/{product_id}/rollout", summary="Configurar rollout")
async def factory_product_rollout(product_id: str, body: dict, request: Request):
    _cc_require(request)
    from src.platform.marketplace.products import rollout_update

    return await rollout_update(UUID(product_id), body)


@cc_router.get("/products/{product_id}/impact", summary="Impacto potencial")
async def factory_product_impact(product_id: str, request: Request):
    _cc_require(request)
    from src.platform.marketplace.products import impact_analysis

    return await impact_analysis(UUID(product_id))


@cc_router.get("/products/{product_id}/analytics", summary="Métricas del producto")
async def factory_product_analytics(product_id: str, request: Request):
    _cc_require(request)
    from src.platform.marketplace.products import impact_analysis

    impact = await impact_analysis(UUID(product_id))
    return {"product_id": product_id, **impact}


# ---------------------------------------------------------------------------
# Control Center — Test lab y composer helpers
# ---------------------------------------------------------------------------
@cc_router.post("/test/output-normalizer", summary="Lab: probar output_map sobre sample")
async def factory_test_normalizer(body: NormalizerIn, request: Request):
    _cc_require(request)
    from src.platform.marketplace.factory import test_output_normalizer

    return {"normalized": test_output_normalizer(body.output_map or {}, body.sample or {})}


# ---------------------------------------------------------------------------
# Tenant — catálogo de productos publicados
# ---------------------------------------------------------------------------
@tenant_router.get("", summary="Catálogo de productos publicados")
async def product_catalog(
    request: Request,
    product_type: str | None = None,
    applies_to: str | None = None,
    category: str | None = None,
    pricing_model: str | None = None,
    q: str | None = None,
):
    _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.products import list_products

    return await list_products(
        product_type=product_type,
        applies_to=applies_to,
        category=category,
        pricing_model=pricing_model,
        q=q,
    )


@tenant_router.get("/installs", summary="Mis instalaciones de productos")
async def product_installs(request: Request, only_updates: bool = False):
    ctx = _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.factory import list_tenant_installs

    return await list_tenant_installs(
        ctx.organization_id, await _workspace_id(request), only_updates=only_updates
    )


@tenant_router.get("/updates", summary="Instalaciones con actualización disponible")
async def product_updates(request: Request):
    ctx = _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.factory import list_tenant_installs

    return await list_tenant_installs(
        ctx.organization_id, await _workspace_id(request), only_updates=True
    )


@tenant_router.get("/categories", summary="Facetas del catálogo")
async def product_facets(request: Request):
    _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.products import catalog_facets

    return await catalog_facets()


@tenant_router.get("/installs/{install_id}", summary="Detalle de instalación (salud real)")
async def product_install_detail(install_id: str, request: Request):
    ctx = _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.factory import refresh_installation_health

    result = await refresh_installation_health(ctx.organization_id, UUID(install_id))
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@tenant_router.get("/installs/{install_id}/impact", summary="Impacto antes de desinstalar")
async def product_install_impact(install_id: str, request: Request):
    ctx = _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.factory import installation_impact

    result = await installation_impact(ctx.organization_id, UUID(install_id))
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@tenant_router.post("/installs/{install_id}/update", summary="Aplicar actualización del producto")
async def product_install_update(install_id: str, request: Request):
    ctx = _tenant_require(request, "marketplace:manage")
    from src.platform.marketplace.factory import update_product_installation

    result = await update_product_installation(ctx.organization_id, UUID(install_id))
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@tenant_router.delete("/installs/{install_id}", summary="Desinstalar producto (muestra impacto)")
async def product_uninstall(install_id: str, request: Request, cascade: bool = False):
    ctx = _tenant_require(request, "marketplace:manage")
    from src.platform.marketplace.factory import uninstall_product

    result = await uninstall_product(ctx.organization_id, UUID(install_id), cascade=cascade)
    if result is None:
        raise HTTPException(404, "Instalación no encontrada")
    return result


@tenant_router.get("/{product_id}", summary="Detalle público de producto")
async def product_catalog_detail(product_id: str, request: Request):
    _tenant_require(request, "marketplace_products:read")
    from src.platform.marketplace.products import get_product

    result: dict | None = None
    try:
        result = await get_product(product_id=UUID(product_id))
    except ValueError:
        result = await get_product(slug=product_id)
    if result is None or result["status"] not in ("PUBLISHED", "READY"):
        raise HTTPException(404, "Producto no encontrado")
    return result


@tenant_router.post("/{product_id}/install", summary="Instalar producto (resuelve dependencias)")
async def product_install(product_id: str, body: InstallProductIn, request: Request):
    ctx = _tenant_require(request, "marketplace:install")
    from src.platform.marketplace.factory import install_product
    from src.platform.marketplace.products import ProductError

    try:
        return await install_product(
            ctx.organization_id,
            UUID(product_id),
            workspace_id=await _workspace_id(request),
            created_by=ctx.user_id,
            install_answers=body.answers,
        )
    except ProductError as exc:
        raise HTTPException(422, str(exc)) from exc


class VersionIn(BaseModel):
    version: int = Field(ge=2, le=999)


class TransitionIn(BaseModel):
    status: str


class NormalizerIn(BaseModel):
    output_map: dict | None = None
    sample: dict | None = None


class InstallProductIn(BaseModel):
    answers: dict | None = None

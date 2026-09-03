# =============================================================================
# AI Agent Marketplace & Ecosystem v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/marketplace", tags=["Marketplace Ecosystem"])


@router.get("", summary="Catálogo público")
async def catalog(request: Request, category: str | None = None, search: str | None = None, limit: int = 50):
    from src.platform.marketplacev2.ecosystem import public_catalog
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await public_catalog(category, search, limit)


@router.get("/{listing_id}", summary="Detalle del listing")
async def listing_detail(listing_id: str, request: Request):
    from src.platform.marketplacev2.ecosystem import listing_detail
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await listing_detail(UUID(listing_id))
    if result is None:
        raise HTTPException(404, "Listing not found")
    return result


@router.post("/listings", summary="Crear publicación")
async def create_listing(body: ListingIn, request: Request):
    from src.platform.marketplacev2.ecosystem import create_listing
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await create_listing(
            ctx.organization_id,
            body.name,
            body.description,
            body.category,
            body.pricing_type,
            body.price_cents,
            body.config_template,
            body.prompt_template,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{listing_id}/publish", summary="Publicar")
async def publish_listing(listing_id: str, request: Request):
    from src.platform.marketplacev2.ecosystem import set_listing_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_listing_status(ctx.organization_id, UUID(listing_id), "published")
    if result is None:
        raise HTTPException(404, "Listing not found")
    return result


@router.post("/{listing_id}/unpublish", summary="Despublicar")
async def unpublish_listing(listing_id: str, request: Request):
    from src.platform.marketplacev2.ecosystem import set_listing_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_listing_status(ctx.organization_id, UUID(listing_id), "unpublished")
    if result is None:
        raise HTTPException(404, "Listing not found")
    return result


@router.patch("/{listing_id}", summary="Actualizar publicación")
async def update_listing(listing_id: str, body: ListingUpdateIn, request: Request):
    from src.platform.marketplacev2.ecosystem import update_listing
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await update_listing(
        ctx.organization_id,
        UUID(listing_id),
        body.name,
        body.description,
        body.category,
        body.pricing_type,
        body.price_cents,
        body.screenshot_urls,
    )
    if result is None:
        raise HTTPException(404, "Listing not found")
    return result


@router.post("/{listing_id}/versions", summary="Nueva versión")
async def new_version(listing_id: str, body: VersionIn, request: Request):
    from src.platform.marketplacev2.ecosystem import new_listing_version
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await new_listing_version(
        ctx.organization_id,
        UUID(listing_id),
        body.version,
        body.changelog,
        body.config_template,
        body.prompt_template,
    )
    if result is None:
        raise HTTPException(404, "Listing not found")
    return result


@router.get("/my/listings", summary="Mis publicaciones")
async def my_listings(request: Request):
    from src.platform.marketplacev2.ecosystem import my_listings
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await my_listings(ctx.organization_id)


@router.post("/{listing_id}/reviews", summary="Escribir review")
async def add_review(listing_id: str, body: ReviewIn, request: Request):
    from src.platform.marketplacev2.ecosystem import add_review
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    try:
        return await add_review(ctx.organization_id, UUID(listing_id), body.rating, body.comment)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{listing_id}/reviews", summary="Reviews del listing")
async def list_reviews(listing_id: str, request: Request):
    from src.platform.marketplacev2.ecosystem import list_reviews
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_reviews(UUID(listing_id))


@router.post("/{listing_id}/purchase", summary="Comprar listing")
async def purchase_listing(listing_id: str, request: Request):
    from src.platform.marketplacev2.ecosystem import purchase
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    return await purchase(ctx.organization_id, UUID(listing_id))


@router.get("/my/purchases", summary="Mis compras")
async def my_purchases(request: Request):
    from src.platform.marketplacev2.ecosystem import my_purchases
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await my_purchases(ctx.organization_id)


@router.get("/my/payouts", summary="Mis payouts")
async def my_payouts(request: Request):
    from src.platform.marketplacev2.ecosystem import list_payouts
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_payouts(ctx.organization_id)


@router.post("/partner/apply", summary="Aplicar a programa de partner")
async def partner_apply(body: PartnerIn, request: Request):
    from src.platform.marketplacev2.ecosystem import apply_partner
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await apply_partner(ctx.organization_id, body.level)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/partner/badges", summary="Mi badge de partner")
async def partner_badges(request: Request):
    from src.platform.marketplacev2.ecosystem import partner_badges
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await partner_badges(ctx.organization_id)


class ListingIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    category: str = Field(default="general", max_length=40)
    pricing_type: str = Field(default="free", pattern="^(free|one_time|subscription)$")
    price_cents: int = Field(default=0, ge=0)
    config_template: dict | None = None
    prompt_template: str | None = None


class ListingUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    category: str | None = Field(default=None, max_length=40)
    pricing_type: str | None = Field(default=None, pattern="^(free|one_time|subscription)$")
    price_cents: int | None = Field(default=None, ge=0)
    screenshot_urls: list[str] | None = None


class VersionIn(BaseModel):
    version: str = Field(min_length=1, max_length=20)
    changelog: str | None = None
    config_template: dict | None = None
    prompt_template: str | None = None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class PartnerIn(BaseModel):
    level: str = Field(default="builder", pattern="^(builder|partner|premier)$")

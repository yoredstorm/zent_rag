# =============================================================================
# AI Knowledge Hub v2 — Auto-Discovery & Curation.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge-hub", tags=["Knowledge Hub"])


@router.get("/sources", summary="Fuentes del tenant")
async def hub_sources_list(request: Request):
    from src.platform.knowledgehub.hub import list_sources
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_sources(ctx.organization_id)


@router.post("/sources", summary="Crear fuente")
async def hub_sources_create(body: SourceIn, request: Request):
    from src.platform.knowledgehub.hub import create_source
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await create_source(
            ctx.organization_id, body.name, body.source_type, body.config, body.refresh_interval_h
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/sources/{source_id}", summary="Detalle de fuente")
async def hub_source_detail(source_id: str, request: Request):
    from src.platform.knowledgehub.hub import get_source
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    result = await get_source(ctx.organization_id, UUID(source_id))
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.patch("/sources/{source_id}", summary="Actualizar fuente")
async def hub_source_update(source_id: str, body: SourceUpdateIn, request: Request):
    from src.platform.knowledgehub.hub import update_source
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await update_source(
        ctx.organization_id, UUID(source_id), body.name, body.config, body.refresh_interval_h
    )
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.delete("/sources/{source_id}", summary="Eliminar fuente")
async def hub_source_delete(source_id: str, request: Request):
    from src.platform.knowledgehub.hub import delete_source
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    if not await delete_source(ctx.organization_id, UUID(source_id)):
        raise HTTPException(404, "Source not found")
    return {"deleted": True}


@router.post("/sources/{source_id}/refresh", summary="Refrescar fuente")
async def hub_source_refresh(source_id: str, request: Request):
    from src.platform.knowledgehub.hub import refresh_source
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await refresh_source(ctx.organization_id, UUID(source_id))
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.get("/sources/{source_id}/refreshes", summary="Historial de refrescos")
async def hub_source_refreshes(source_id: str, request: Request, limit: int = 20):
    from src.platform.knowledgehub.hub import refresh_history
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await refresh_history(ctx.organization_id, UUID(source_id), limit)


@router.post("/sources/{source_id}/pause", summary="Pausar fuente")
async def hub_source_pause(source_id: str, request: Request):
    from src.platform.knowledgehub.hub import set_source_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_source_status(ctx.organization_id, UUID(source_id), "paused")
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.post("/sources/{source_id}/resume", summary="Reanudar fuente")
async def hub_source_resume(source_id: str, request: Request):
    from src.platform.knowledgehub.hub import set_source_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_source_status(ctx.organization_id, UUID(source_id), "active")
    if result is None:
        raise HTTPException(404, "Source not found")
    return result


@router.post("/documents/{document_id}/curate", summary="Curar documento")
async def hub_document_curate(document_id: str, body: CurateIn, request: Request):
    from src.platform.knowledgehub.hub import curate_document
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await curate_document(
        ctx.organization_id,
        UUID(document_id),
        body.category,
        body.author,
        body.confidence,
        body.title,
    )
    if result is None:
        raise HTTPException(404, "Document not found")
    return result


@router.get("/gaps", summary="Huecos de conocimiento")
async def hub_gaps(request: Request, status: str = "open"):
    from src.platform.knowledgehub.hub import list_gaps
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_gaps(ctx.organization_id, status)


@router.post("/gaps/{gap_id}/resolve", summary="Resolver hueco")
async def hub_gap_resolve(gap_id: str, request: Request):
    from src.platform.knowledgehub.hub import resolve_gap
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await resolve_gap(ctx.organization_id, UUID(gap_id))
    if result is None:
        raise HTTPException(404, "Gap not found")
    return result


@router.get("/coverage", summary="Cobertura de conocimiento")
async def hub_coverage(request: Request):
    from src.platform.knowledgehub.hub import coverage_dashboard
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await coverage_dashboard(ctx.organization_id)


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    source_type: str = Field(default="url", pattern="^(url|rss|repo|s3|manual)$")
    config: dict | None = None
    refresh_interval_h: int = Field(default=24, ge=1, le=720)


class SourceUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    config: dict | None = None
    refresh_interval_h: int | None = Field(default=None, ge=1, le=720)


class CurateIn(BaseModel):
    category: str | None = Field(default=None, max_length=60)
    author: str | None = Field(default=None, max_length=120)
    confidence: float | None = Field(default=None, ge=0, le=100)
    title: str | None = Field(default=None, max_length=300)

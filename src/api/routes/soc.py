# =============================================================================
# AI Security Operations Center (SOC) v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/soc", tags=["SOC"])


@router.post("/scan", summary="Detección en tiempo real")
async def soc_scan(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import scan_organization

    ctx = require_permission(request, "billing:read")
    return await scan_organization(ctx.organization_id)


@router.get("/events", summary="Eventos de seguridad")
async def soc_events(request: Request, status: str | None = None):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import list_events

    ctx = require_permission(request, "billing:read")
    return await list_events(ctx.organization_id, status)


@router.get("/events/{event_id}", summary="Detalle del evento")
async def soc_event_detail(event_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import event_detail

    ctx = require_permission(request, "billing:read")
    result = await event_detail(ctx.organization_id, UUID(event_id))
    if result is None:
        raise HTTPException(404, "Event not found")
    return result


@router.post("/events/{event_id}/respond", summary="Respuesta automática")
async def soc_respond(event_id: str, body: RespondIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import respond

    ctx = require_permission(request, "billing:write")
    try:
        result = await respond(ctx.organization_id, UUID(event_id), body.action_type)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Event not found")
    return result


@router.post("/events/{event_id}/resolve", summary="Resolver evento")
async def soc_resolve(event_id: str, body: ResolveIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import resolve_event

    ctx = require_permission(request, "billing:write")
    try:
        result = await resolve_event(ctx.organization_id, UUID(event_id), body.verdict)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "Event not found")
    return result


@router.get("/posture", summary="Postura de seguridad")
async def soc_posture(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import security_posture

    ctx = require_permission(request, "billing:read")
    return await security_posture(ctx.organization_id)


@router.get("/posture/trend", summary="Tendencia de postura")
async def soc_trend(request: Request, days: int = 30):
    from src.platform.rbac.policy import require_permission
    from src.platform.soc.soc import posture_trend

    ctx = require_permission(request, "billing:read")
    return await posture_trend(ctx.organization_id, min(max(days, 1), 90))


class RespondIn(BaseModel):
    action_type: str = Field(pattern="^(revoke_key|block_deployment|throttle|alert)$")


class ResolveIn(BaseModel):
    verdict: str = Field(default="resolved", pattern="^(resolved|false_positive)$")

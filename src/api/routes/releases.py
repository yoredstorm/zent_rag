# =============================================================================
# AI Agent Versioning & Rollout v2 — releases, diff y promoción.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/releases", tags=["Releases"])


@router.get("/versions/{agent_id}", summary="Historial de versiones del agente")
async def tenant_releases_versions(agent_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import list_versions

    ctx = require_permission(request, "billing:read")
    return await list_versions(UUID(agent_id))


@router.get("/diff/{agent_id}", summary="Diff entre dos versiones")
async def tenant_releases_diff(agent_id: str, request: Request, a: str, b: str):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import diff_versions

    ctx = require_permission(request, "billing:read")
    result = await diff_versions(UUID(agent_id), UUID(a), UUID(b))
    if result is None:
        raise HTTPException(404, "Versions not found")
    return result


@router.get("", summary="Releases del tenant")
async def tenant_releases_list(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import list_releases

    ctx = require_permission(request, "billing:read")
    return await list_releases()


@router.post("/start", summary="Iniciar release (canary/stable)")
async def tenant_release_start(body: ReleaseStartIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import start_release

    ctx = require_permission(request, "billing:write")
    try:
        return await start_release(
            UUID(body.agent_id), UUID(body.version_id), body.channel, body.traffic_pct, body.notes
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{release_id}", summary="Detalle del release con eventos")
async def tenant_release_detail(release_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import release_detail

    ctx = require_permission(request, "billing:read")
    result = await release_detail(UUID(release_id))
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


@router.post("/{release_id}/health", summary="Evaluar health-gate")
async def tenant_release_health(release_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import health_check

    ctx = require_permission(request, "billing:read")
    result = await health_check(UUID(release_id))
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


@router.post("/{release_id}/promote", summary="Promover a stable")
async def tenant_release_promote(release_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import promote

    ctx = require_permission(request, "billing:write")
    result = await promote(UUID(release_id), ctx.user_id)
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


@router.post("/{release_id}/rollback", summary="Rollback a la versión anterior")
async def tenant_release_rollback(release_id: str, request: Request, detail: str | None = None):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import rollback

    ctx = require_permission(request, "billing:write")
    result = await rollback(UUID(release_id), detail)
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


@router.post("/{release_id}/pause", summary="Pausar release")
async def tenant_release_pause(release_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import pause_release

    ctx = require_permission(request, "billing:write")
    result = await pause_release(UUID(release_id))
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


@router.post("/{release_id}/resume", summary="Reanudar release")
async def tenant_release_resume(release_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.releases.releases import resume_release

    ctx = require_permission(request, "billing:write")
    result = await resume_release(UUID(release_id))
    if result is None:
        raise HTTPException(404, "Release not found")
    return result


class ReleaseStartIn(BaseModel):
    agent_id: str
    version_id: str
    channel: str = Field(default="canary", pattern="^(canary|stable)$")
    traffic_pct: int = Field(default=100, ge=0, le=100)
    notes: str | None = Field(default=None, max_length=500)

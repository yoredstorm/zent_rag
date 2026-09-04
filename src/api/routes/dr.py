# =============================================================================
# AI Disaster Recovery & High Availability v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/dr", tags=["Disaster Recovery"])


@router.get("/policies", summary="Políticas de DR")
async def dr_policies(request: Request):
    from src.platform.dr.dr_center import list_policies
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_policies(ctx.organization_id)


@router.post("/policies", summary="Crear política de DR")
async def dr_policy_create(body: PolicyIn, request: Request):
    from src.platform.dr.dr_center import create_policy
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await create_policy(
            ctx.organization_id,
            body.name,
            body.scope,
            UUID(body.target_id) if body.target_id else None,
            body.rpo_minutes,
            body.rto_minutes,
            body.replication_region,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/policies/{policy_id}", summary="Actualizar política")
async def dr_policy_update(policy_id: str, body: PolicyUpdateIn, request: Request):
    from src.platform.dr.dr_center import update_policy
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await update_policy(
        ctx.organization_id,
        UUID(policy_id),
        body.name,
        body.rpo_minutes,
        body.rto_minutes,
        body.replication_region,
    )
    if result is None:
        raise HTTPException(404, "Policy not found")
    return result


@router.post("/policies/{policy_id}/pause", summary="Pausar política")
async def dr_policy_pause(policy_id: str, request: Request):
    from src.platform.dr.dr_center import set_policy_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_policy_status(ctx.organization_id, UUID(policy_id), "paused")
    if result is None:
        raise HTTPException(404, "Policy not found")
    return result


@router.post("/policies/{policy_id}/resume", summary="Reanudar política")
async def dr_policy_resume(policy_id: str, request: Request):
    from src.platform.dr.dr_center import set_policy_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await set_policy_status(ctx.organization_id, UUID(policy_id), "active")
    if result is None:
        raise HTTPException(404, "Policy not found")
    return result


@router.post("/backups", summary="Crear backup")
async def dr_backup_create(body: BackupIn, request: Request):
    from src.platform.dr.dr_center import create_backup
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await create_backup(
            ctx.organization_id, body.scope, UUID(body.source_id) if body.source_id else None
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/backups", summary="Listar backups")
async def dr_backups(request: Request, scope: str | None = None, limit: int = 50):
    from src.platform.dr.dr_center import list_backups
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_backups(ctx.organization_id, scope, limit)


@router.post("/backups/{backup_id}/restore", summary="Restaurar backup")
async def dr_backup_restore(backup_id: str, body: RestoreIn, request: Request):
    from src.platform.dr.dr_center import restore_backup
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await restore_backup(ctx.organization_id, UUID(backup_id), body.region)
    if result is None:
        raise HTTPException(404, "Backup not found")
    return result


@router.post("/drills", summary="Ejecutar drill de failover")
async def dr_drill_run(body: DrillIn, request: Request):
    from src.platform.dr.dr_center import run_drill
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await run_drill(ctx.organization_id, UUID(body.policy_id), body.region)
    if result is None:
        raise HTTPException(404, "Policy not found")
    return result


@router.get("/drills", summary="Historial de drills")
async def dr_drills(request: Request, limit: int = 50):
    from src.platform.dr.dr_center import list_drills
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_drills(ctx.organization_id, limit)


@router.get("/availability", summary="Dashboard de disponibilidad")
async def dr_availability(request: Request):
    from src.platform.dr.dr_center import availability_dashboard
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await availability_dashboard(ctx.organization_id)


class PolicyIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    scope: str = Field(default="agent", pattern="^(agent|knowledge|full)$")
    target_id: str | None = None
    rpo_minutes: int = Field(default=60, ge=1, le=10080)
    rto_minutes: int = Field(default=15, ge=1, le=1440)
    replication_region: str = Field(default="eu-west-1", max_length=40)


class PolicyUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    rpo_minutes: int | None = Field(default=None, ge=1, le=10080)
    rto_minutes: int | None = Field(default=None, ge=1, le=1440)
    replication_region: str | None = Field(default=None, max_length=40)


class BackupIn(BaseModel):
    scope: str = Field(pattern="^(agent|knowledge|full)$")
    source_id: str | None = None


class RestoreIn(BaseModel):
    region: str = Field(default="us-east-1", max_length=40)


class DrillIn(BaseModel):
    policy_id: str
    region: str | None = Field(default=None, max_length=40)

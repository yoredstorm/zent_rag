# =============================================================================
# Demo transition + workspace reset
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_workspace_repo
from src.core.ports import WorkspaceRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.demo_purge.service import DemoPurgeService
from src.platform.demo_transition.service import DemoTransitionService
from src.platform.rbac.policy import require_permission
from src.platform.workspaces.context import resolve_workspace
from src.platform.workspaces.step_up import require_tenant_step_up

router = APIRouter(prefix="/api/v1/demo-transition", tags=["Demo Transition"])


class StartMyDataRequest(BaseModel):
    mode: str = Field(..., pattern="^(new_workspace|purge)$")
    confirmation: str | None = None
    name: str = "My Business"


class ResetRequest(BaseModel):
    confirmation: str = Field(..., min_length=3)
    documents: bool = False
    sources: bool = False
    semantic: bool = False
    agents: bool = False
    all_business_data: bool = False


def _svc(repo: WorkspaceRepository) -> DemoTransitionService:
    return DemoTransitionService(repo)


@router.get("/status", summary="¿El workspace activo es demo?")
async def transition_status(request: Request):
    require_permission(request, "workspaces:read")
    ws = await resolve_workspace(request)
    return {
        "workspace_id": str(ws.id),
        "kind": getattr(ws.kind, "value", str(ws.kind)),
        "is_demo": getattr(ws.kind, "value", str(ws.kind)) == "demo",
        "name": ws.name,
    }


@router.get("/impact", summary="Resumen de impacto si se purga el demo")
async def transition_impact(
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    require_permission(request, "workspaces:read")
    ws = await resolve_workspace(request)
    return await DemoPurgeService().impact(ctx_org(request), ws.id)


def ctx_org(request: Request) -> UUID:
    ctx = require_permission(request, "workspaces:read")
    return ctx.organization_id


@router.post("/start-with-my-data", summary="Start with My Data")
async def start_with_my_data(
    body: StartMyDataRequest,
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    ctx = require_permission(request, "workspaces:write")
    ws = await resolve_workspace(request)
    svc = _svc(repo)
    if body.mode == "new_workspace":
        created = await svc.start_business_workspace(ctx, name=body.name)
        return {
            "mode": "new_workspace",
            "workspace": {
                "id": str(created.id),
                "name": created.name,
                "kind": created.kind.value,
            },
            "welcome": "Welcome to your business workspace.",
        }
    await require_tenant_step_up(request)
    try:
        result = await svc.replace_demo(ctx, ws.id, body.confirmation or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"mode": "purge", "welcome": "Welcome to your business workspace.", **result}


@router.post("/reset", summary="Reset data del workspace activo")
async def reset_workspace(
    body: ResetRequest,
    request: Request,
):
    ctx = require_permission(request, "workspaces:write")
    if body.confirmation.strip().upper() not in {"RESET", "FULL RESET", "DELETE DEMO"}:
        raise HTTPException(400, "confirmation required")
    await require_tenant_step_up(request)
    ws = await resolve_workspace(request)
    full = body.all_business_data
    result = await DemoPurgeService(
        AuditLogService(PostgresAuditLogRepository())
    ).purge(
        ctx,
        ws.id,
        action="workspace.reset",
        options={
            "documents": body.documents or full,
            "sources": body.sources or full,
            "semantic": body.semantic or full,
            "agents": body.agents or full,
            "all_business_data": full,
        },
    )
    return result

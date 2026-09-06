"""FASE 03 — HITL approvals + workspace collaboration routes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/v1", tags=["Approvals & Workspace"])


@router.get("/approvals", summary="Aprobaciones pendientes (FASE 03)")
async def list_approvals(request: Request, status: str | None = None):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import list_approvals as _list
    from src.platform.rbac.policy import require_organization_admin

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    return {"approvals": await _list(organization_id, status=status)}


@router.post("/approvals/{approval_id}/decide", summary="Aprobar/rechazar (FASE 03)")
async def decide_approval(approval_id: str, body: dict, request: Request):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import decide_approval as _decide
    from src.platform.rbac.policy import require_organization_admin

    ctx = require_organization_admin(request)
    organization_id = resolve_organization(request)
    try:
        aid = UUID(approval_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid approval id") from exc
    approved = bool(body.get("approved", True))
    if not await _decide(organization_id, aid, approved, decided_by=ctx.user_id):
        raise HTTPException(409, "Aprobación no pendiente o inexistente")
    return {"status": "approved" if approved else "rejected"}


@router.get("/workspaces/{workspace_id}/tasks", summary="Tasks del workspace (FASE 03)")
async def get_workspace_tasks(workspace_id: str, request: Request):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import list_tasks
    from src.platform.rbac.policy import require_permission
    from src.platform.workspaces.service import require_own_workspace

    ctx = require_permission(request, "workspaces:read")
    organization_id = resolve_organization(request)
    try:
        wid = UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid workspace id") from exc
    await require_own_workspace(organization_id, wid)
    return {"tasks": await list_tasks(wid)}


@router.post("/workspaces/{workspace_id}/tasks", summary="Crear task (FASE 03)")
async def create_workspace_task(workspace_id: str, body: dict, request: Request):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import create_task
    from src.platform.rbac.policy import require_permission
    from src.platform.workspaces.service import require_own_workspace

    ctx = require_permission(request, "workspaces:write")
    organization_id = resolve_organization(request)
    try:
        wid = UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid workspace id") from exc
    await require_own_workspace(organization_id, wid)
    title = str(body.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title requerido")
    agent_id = body.get("agent_id")
    task = await create_task(
        organization_id,
        wid,
        title,
        created_by=ctx.user_id,
        agent_id=UUID(agent_id) if agent_id else None,
    )
    return {"task": task}


@router.put("/workspaces/{workspace_id}/tasks/{task_id}", summary="Actualizar task (FASE 03)")
async def update_workspace_task(workspace_id: str, task_id: str, body: dict, request: Request):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import update_task_status
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:write")
    organization_id = resolve_organization(request)
    status = str(body.get("status") or "")
    if status not in ("todo", "in_progress", "done"):
        raise HTTPException(400, "status inválido")
    try:
        tid = UUID(task_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid task id") from exc
    if not await update_task_status(organization_id, tid, status, actor=ctx.user_id):
        raise HTTPException(404, "Task no encontrada")
    return {"status": status}


@router.get("/workspaces/{workspace_id}/activity", summary="Actividad del workspace (FASE 03)")
async def get_workspace_activity(workspace_id: str, request: Request):
    from src.api.security import resolve_organization
    from src.platform.approvals.service import workspace_activity
    from src.platform.rbac.policy import require_permission
    from src.platform.workspaces.service import require_own_workspace

    ctx = require_permission(request, "workspaces:read")
    organization_id = resolve_organization(request)
    try:
        wid = UUID(workspace_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid workspace id") from exc
    await require_own_workspace(organization_id, wid)
    return {"activity": await workspace_activity(wid)}

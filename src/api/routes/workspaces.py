# =============================================================================
# Workspaces Routes — Tenant → Workspace → {Agents, KBs, Connectors}
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_workspace_repo
from src.core.ports import WorkspaceRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService
from src.platform.workspaces.service import (
    ensure_default_workspace,
    workspace_slugify,
)

router = APIRouter(prefix="/api/v1/workspaces", tags=["Workspaces"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


def _workspace_response(ws, counts: dict | None = None) -> dict:
    return {
        "id": str(ws.id),
        "name": ws.name,
        "slug": ws.slug,
        "description": ws.description,
        "status": ws.status.value,
        "created_at": ws.created_at.isoformat(),
        "counts": (counts or {}).get(ws.id, {}),
    }


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


@router.get("", summary="Listar workspaces (auto-crea el default)")
async def list_workspaces(
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:read")
    await ensure_default_workspace(repo, ctx.organization_id)
    workspaces = await repo.list_workspaces(ctx.organization_id)
    counts = await repo.workspace_counts(ctx.organization_id)
    return {
        "workspaces": [_workspace_response(w, counts) for w in workspaces],
        "count": len(workspaces),
    }


@router.post("", status_code=201, summary="Crear workspace")
async def create_workspace(
    body: CreateWorkspaceRequest,
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:write")
    slug = workspace_slugify(body.name)
    existing = await repo.get_workspace_by_slug(ctx.organization_id, slug)
    if existing is not None:
        raise HTTPException(409, "Workspace slug already exists")
    ws = await repo.create_workspace(
        ctx.organization_id,
        body.name,
        slug,
        description=body.description,
        created_by=ctx.user_id,
    )
    await _audit().write(
        ctx,
        "workspace.created",
        "workspace",
        ws.id,
        metadata={"name": ws.name, "slug": ws.slug},
    )
    counts = await repo.workspace_counts(ctx.organization_id)
    return _workspace_response(ws, counts)


@router.get("/{workspace_id}", summary="Obtener workspace")
async def get_workspace(
    workspace_id: str,
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:read")
    try:
        wid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(400, "workspace_id must be a valid UUID")
    ws = await repo.get_workspace(ctx.organization_id, wid)
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    counts = await repo.workspace_counts(ctx.organization_id)
    return _workspace_response(ws, counts)


@router.put("/{workspace_id}", summary="Actualizar workspace")
async def update_workspace(
    workspace_id: str,
    body: UpdateWorkspaceRequest,
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:write")
    try:
        wid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(400, "workspace_id must be a valid UUID")
    fields = body.model_dump(exclude_none=True)
    ws = await repo.update_workspace(ctx.organization_id, wid, **fields)
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    await _audit().write(
        ctx,
        "workspace.updated",
        "workspace",
        wid,
        metadata={"fields": list(fields.keys())},
    )
    return _workspace_response(ws)


@router.delete("/{workspace_id}", summary="Archivar workspace")
async def archive_workspace(
    workspace_id: str,
    request: Request,
    repo: WorkspaceRepository = Depends(get_workspace_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:write")
    try:
        wid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(400, "workspace_id must be a valid UUID")
    ws = await repo.update_workspace(ctx.organization_id, wid, status="archived")
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    await _audit().write(
        ctx, "workspace.archived", "workspace", wid, metadata={"name": ws.name}
    )
    return {"status": "archived", "workspace_id": str(wid)}

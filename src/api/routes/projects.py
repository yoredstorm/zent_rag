# =============================================================================
# Projects Routes — CRUD de proyectos (organization-scoped)
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import get_project_repo
from src.core.ports import ProjectRepository
from src.infrastructure.postgres.relational_db import PostgresAuditLogRepository
from src.platform.audit.service import AuditLogService

router = APIRouter(prefix="/api/v1/projects", tags=["Projects"])


def _audit() -> AuditLogService:
    return AuditLogService(PostgresAuditLogRepository())


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


@router.get("", summary="Listar proyectos de la organización")
async def list_projects(
    request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "projects:read")
    projects = await repo.list_projects(ctx.organization_id)
    return {
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "description": p.description,
                "created_at": p.created_at.isoformat(),
            }
            for p in projects
        ],
        "count": len(projects),
    }


@router.post("", status_code=201, summary="Crear proyecto")
async def create_project(
    body: CreateProjectRequest,
    request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "projects:write")
    project = await repo.create_project(ctx.organization_id, body.name, body.description)
    await _audit().write(
        ctx, "project.created", "project", project.id,
        metadata={"name": project.name},
    )
    return {"id": str(project.id), "name": project.name, "description": project.description}


@router.get("/{project_id}", summary="Obtener proyecto")
async def get_project(
    project_id: str,
    request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "projects:read")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "project_id must be a valid UUID")
    project = await repo.get_project(ctx.organization_id, pid)
    if project is None:
        # 404 (no 403): no revelar existencia de recursos de otra organización
        raise HTTPException(404, "Project not found")
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at.isoformat(),
    }


@router.put("/{project_id}", summary="Actualizar proyecto")
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "projects:write")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "project_id must be a valid UUID")
    try:
        project = await repo.update_project(
            ctx.organization_id, pid, name=body.name, description=body.description
        )
    except ValueError:
        raise HTTPException(404, "Project not found")
    await _audit().write(
        ctx, "project.updated", "project", pid,
        metadata={"name": project.name},
    )
    return {"id": str(project.id), "name": project.name, "description": project.description}


@router.delete("/{project_id}", summary="Eliminar proyecto")
async def delete_project(
    project_id: str,
    request: Request,
    repo: ProjectRepository = Depends(get_project_repo),
):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "projects:write")
    try:
        pid = UUID(project_id)
    except ValueError:
        raise HTTPException(400, "project_id must be a valid UUID")
    if await repo.get_project(ctx.organization_id, pid) is None:
        raise HTTPException(404, "Project not found")
    await repo.delete_project(ctx.organization_id, pid)
    await _audit().write(ctx, "project.deleted", "project", pid)
    return {"status": "deleted", "project_id": str(pid)}

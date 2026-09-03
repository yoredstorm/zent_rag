# =============================================================================
# AI Workflow Automation Studio v2 — CRUD, ejecución y trazabilidad.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/workflows", tags=["Workflows"])


@router.get("", summary="Workflows del tenant")
async def tenant_workflows_list(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_workflows

    ctx = require_permission(request, "billing:read")
    return await list_workflows(ctx.organization_id)


@router.post("", summary="Crear workflow")
async def tenant_workflows_create(body: WorkflowIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import create_workflow

    ctx = require_permission(request, "billing:write")
    try:
        return await create_workflow(
            ctx.organization_id,
            body.name,
            body.trigger_type,
            body.trigger_config,
            body.steps,
            body.description,
            ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/templates", summary="Plantillas de workflows")
async def tenant_workflow_templates(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_templates

    ctx = require_permission(request, "billing:read")
    return await list_templates()


@router.post("/templates/{slug}/install", summary="Crear desde plantilla")
async def tenant_workflow_template_install(slug: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import create_from_template

    ctx = require_permission(request, "billing:write")
    try:
        return await create_from_template(ctx.organization_id, slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{workflow_id}", summary="Detalle del workflow")
async def tenant_workflow_detail(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import get_workflow

    ctx = require_permission(request, "billing:read")
    result = await get_workflow(ctx.organization_id, UUID(workflow_id))
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.patch("/{workflow_id}", summary="Actualizar workflow")
async def tenant_workflow_update(workflow_id: str, body: WorkflowUpdateIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import update_workflow

    ctx = require_permission(request, "billing:write")
    result = await update_workflow(
        ctx.organization_id,
        UUID(workflow_id),
        body.name,
        body.description,
        body.trigger_config,
        body.steps,
    )
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.delete("/{workflow_id}", summary="Eliminar workflow")
async def tenant_workflow_delete(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import delete_workflow

    ctx = require_permission(request, "billing:write")
    if not await delete_workflow(ctx.organization_id, UUID(workflow_id)):
        raise HTTPException(404, "Workflow not found")
    return {"deleted": True}


@router.post("/{workflow_id}/activate", summary="Activar workflow")
async def tenant_workflow_activate(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import set_workflow_status

    ctx = require_permission(request, "billing:write")
    result = await set_workflow_status(ctx.organization_id, UUID(workflow_id), "active")
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/pause", summary="Pausar workflow")
async def tenant_workflow_pause(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import set_workflow_status

    ctx = require_permission(request, "billing:write")
    result = await set_workflow_status(ctx.organization_id, UUID(workflow_id), "paused")
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.post("/{workflow_id}/run", summary="Ejecutar workflow")
async def tenant_workflow_run(workflow_id: str, body: RunIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import run_workflow

    ctx = require_permission(request, "billing:write")
    result = await run_workflow(UUID(workflow_id), body.payload)
    if result is None:
        raise HTTPException(404, "Workflow not found")
    return result


@router.get("/{workflow_id}/runs", summary="Runs del workflow")
async def tenant_workflow_runs(workflow_id: str, request: Request, limit: int = 50):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import list_runs

    ctx = require_permission(request, "billing:read")
    return await list_runs(ctx.organization_id, UUID(workflow_id), limit)


@router.get("/runs/{run_id}", summary="Detalle del run con pasos")
async def tenant_workflow_run_detail(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.engine import run_detail

    ctx = require_permission(request, "billing:read")
    result = await run_detail(ctx.organization_id, UUID(run_id))
    if result is None:
        raise HTTPException(404, "Run not found")
    return result


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    trigger_type: str = Field(default="webhook", pattern="^(webhook|schedule|event)$")
    trigger_config: dict | None = None
    steps: list[dict] = Field(default_factory=list)


class WorkflowUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=150)
    description: str | None = None
    trigger_config: dict | None = None
    steps: list[dict] | None = None


class RunIn(BaseModel):
    payload: dict | None = None

# =============================================================================
# Workflows (tenant) — definiciones, triggers, runs, aprobaciones
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


class WorkflowStepIn(BaseModel):
    type: str = Field(..., pattern="^(ingest|evaluate|deploy|notify|webhook|approval)$")
    params: dict = Field(default_factory=dict)


class WorkflowIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    trigger_type: str = Field(default="manual", pattern="^(manual|schedule|event)$")
    cron_expr: str | None = None
    steps: list[WorkflowStepIn] = Field(default_factory=list, min_length=1)


@router.post("", status_code=201, summary="Crear workflow")
async def create_workflow(body: WorkflowIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import create_definition

    ctx = require_permission(request, "agents:write")
    try:
        result = await create_definition(
            ctx.organization_id,
            body.name,
            body.description,
            body.trigger_type,
            body.cron_expr,
            [s.model_dump() for s in body.steps],
            created_by=ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


@router.get("", summary="Listar workflows")
async def list_workflows(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import list_definitions

    ctx = require_permission(request, "agents:read")
    return {"workflows": await list_definitions(ctx.organization_id)}


@router.get("/runs", summary="Runs del tenant")
async def list_runs(request: Request, status: str | None = None, limit: int = 50):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import list_runs as _list_runs

    ctx = require_permission(request, "agents:read")
    runs = await _list_runs(ctx.organization_id, status=status, limit=min(limit, 200))
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_id}", summary="Pasos de un run")
async def get_run(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import get_run_steps

    ctx = require_permission(request, "agents:read")
    return {"steps": await get_run_steps(UUID(run_id))}


@router.post("/runs/{run_id}/approve", summary="Aprobar paso pendiente")
async def approve_run(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import approve_run as _approve

    ctx = require_permission(request, "agents:write")
    result = await _approve(ctx.organization_id, UUID(run_id), approve=True)
    if result["status"] == "not_found":
        raise HTTPException(404, "Run not found")
    return result


@router.post("/runs/{run_id}/reject", summary="Rechazar paso pendiente")
async def reject_run(run_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import approve_run as _approve

    ctx = require_permission(request, "agents:write")
    result = await _approve(ctx.organization_id, UUID(run_id), approve=False)
    if result["status"] == "not_found":
        raise HTTPException(404, "Run not found")
    return result


@router.get("/{workflow_id}", summary="Detalle de workflow")
async def get_workflow(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import get_definition

    ctx = require_permission(request, "agents:read")
    definition = await get_definition(ctx.organization_id, UUID(workflow_id))
    if definition is None:
        raise HTTPException(404, "Workflow not found")
    return definition


@router.put("/{workflow_id}", summary="Actualizar workflow")
async def update_workflow(workflow_id: str, body: WorkflowIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import update_definition

    ctx = require_permission(request, "agents:write")
    ok = await update_definition(
        ctx.organization_id,
        UUID(workflow_id),
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        cron_expr=body.cron_expr,
        steps=[s.model_dump() for s in body.steps],
    )
    if not ok:
        raise HTTPException(404, "Workflow not found")
    return {"status": "updated"}


@router.delete("/{workflow_id}", summary="Eliminar workflow")
async def delete_workflow(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import delete_definition

    ctx = require_permission(request, "agents:write")
    ok = await delete_definition(ctx.organization_id, UUID(workflow_id))
    if not ok:
        raise HTTPException(404, "Workflow not found")
    return {"status": "deleted"}


@router.post("/{workflow_id}/trigger", summary="Ejecutar workflow manualmente")
async def trigger_workflow(workflow_id: str, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.workflows.workflows import trigger_workflow as _trigger

    ctx = require_permission(request, "agents:write")
    result = await _trigger(ctx.organization_id, UUID(workflow_id), trigger="manual", created_by=ctx.user_id)
    if result["status"] == "not_found":
        raise HTTPException(404, "Workflow not found")
    return result



# =============================================================================
# Cognitive OS API — Phase 3 (planning runs)
# =============================================================================
# Gate por RAG_COGNITIVE_OS_ENABLED (off | shadow | limited | active). En esta
# fase el endpoint SOLO planifica (task graph + asignaciones + presupuesto);
# la ejecución de especialistas llega en fases posteriores.
# =============================================================================
from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.core.config import get_settings
from src.core.domain.cognitive import CognitiveBudget, CognitiveScope

router = APIRouter(prefix="/api/v1/cognitive", tags=["cognitive"])

_ENABLED_MODES = {"shadow", "limited", "active"}


class CognitiveBudgetRequest(BaseModel):
    max_agents: int | None = Field(default=None, ge=1)
    max_llm_calls: int | None = Field(default=None, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_seconds: float | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_debate_rounds: int | None = Field(default=None, ge=0)


class CognitiveRunRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    budget: CognitiveBudgetRequest | None = None


def _require_cognitive_enabled() -> None:
    mode = str(get_settings().COGNITIVE_OS_ENABLED or "off").strip().lower()
    if mode not in _ENABLED_MODES:
        raise HTTPException(
            503,
            "Cognitive OS is disabled (RAG_COGNITIVE_OS_ENABLED=off); "
            "use shadow|limited|active to enable planning",
        )


def _build_budget(request_model: CognitiveBudgetRequest | None) -> CognitiveBudget | None:
    if request_model is None:
        return None
    overrides = {
        key: value
        for key, value in request_model.model_dump().items()
        if value is not None
    }
    try:
        return replace(CognitiveBudget(), **overrides)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def _resolve_scope(request: Request, ctx) -> CognitiveScope:
    from src.platform.workspaces.context import (
        resolve_workspace,
        workspace_header_or_none,
    )

    workspace_id: UUID | None = None
    if workspace_header_or_none(request) is not None:
        workspace_id = (await resolve_workspace(request)).id
    return CognitiveScope(
        organization_id=ctx.organization_id,
        workspace_id=workspace_id,
        user_id=getattr(ctx, "user_id", None),
        role=str(getattr(ctx, "role", "admin")),
    )


@router.post("/runs", status_code=201, summary="Planificar un cognitive run")
async def create_cognitive_run(body: CognitiveRunRequest, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_cognitive_service
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    scope = await _resolve_scope(request, ctx)
    budget = _build_budget(body.budget)
    try:
        return await get_cognitive_service().create_run(
            query=body.query,
            scope=scope,
            budget=budget,
            created_by=getattr(ctx, "user_id", None),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs/{run_id}", summary="Detalle de un cognitive run")
async def get_cognitive_run(run_id: UUID, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_cognitive_service
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    result = await get_cognitive_service().get_run(ctx.organization_id, run_id)
    if result is None:
        raise HTTPException(404, "Cognitive run not found")
    return result


@router.get("/runs/{run_id}/tasks", summary="Tareas del cognitive run")
async def list_cognitive_tasks(run_id: UUID, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_cognitive_service
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    tasks = await get_cognitive_service().list_tasks(ctx.organization_id, run_id)
    if tasks is None:
        raise HTTPException(404, "Cognitive run not found")
    return {"tasks": tasks}


@router.get("/runs/{run_id}/messages", summary="Mensajes del cognitive run")
async def list_cognitive_messages(run_id: UUID, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_cognitive_service
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    messages = await get_cognitive_service().list_messages(
        ctx.organization_id, run_id
    )
    if messages is None:
        raise HTTPException(404, "Cognitive run not found")
    return {"messages": messages}

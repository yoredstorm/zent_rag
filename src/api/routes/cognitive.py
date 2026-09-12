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


class SuggestionDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(default="", max_length=2000)


class ShadowRunRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)


def _suggestion_to_dict(suggestion) -> dict:
    return {
        "id": str(suggestion.id),
        "kind": suggestion.kind.value,
        "status": suggestion.status.value,
        "title": suggestion.title,
        "reasoning": suggestion.reasoning,
        "run_id": str(suggestion.run_id) if suggestion.run_id else None,
        "claim_ids": [str(c) for c in suggestion.claim_ids],
        "provenance": suggestion.provenance.value,
        "confidence": suggestion.confidence,
        "decided_by": str(suggestion.decided_by) if suggestion.decided_by else None,
        "created_at": suggestion.created_at.isoformat(),
    }


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


def _scope_from_run(run: dict, fallback_org: UUID, fallback_user) -> CognitiveScope:
    scope = run.get("scope") or {}
    return CognitiveScope(
        organization_id=UUID(str(scope.get("organization_id") or fallback_org)),
        workspace_id=_uuid_or_none(scope.get("workspace_id")),
        user_id=_uuid_or_none(scope.get("user_id")) or fallback_user,
        role=str(scope.get("role") or "admin"),
        groups=tuple(str(g) for g in (scope.get("groups") or [])),
    )


def _uuid_or_none(value) -> UUID | None:
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


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


@router.post(
    "/runs/{run_id}/execute",
    summary="Ejecutar un cognitive run planificado (fase 4)",
)
async def execute_cognitive_run(run_id: UUID, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_cognitive_executor, get_cognitive_service
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    service = get_cognitive_service()
    current = await service.get_run(ctx.organization_id, run_id)
    if current is None:
        raise HTTPException(404, "Cognitive run not found")
    if current["run"]["status"] != "planned":
        raise HTTPException(
            409,
            f"cognitive run status '{current['run']['status']}' cannot execute",
        )
    scope = _scope_from_run(
        current["run"], ctx.organization_id, getattr(ctx, "user_id", None)
    )
    try:
        return await get_cognitive_executor().execute_run(
            organization_id=ctx.organization_id, run_id=run_id, scope=scope
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(
    "/runs/{run_id}/curate",
    summary="Generar sugerencias gobernadas desde un run (fase 7)",
)
async def curate_cognitive_run(run_id: UUID, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_knowledge_curator
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    try:
        suggestions = await get_knowledge_curator().propose_from_run(
            ctx.organization_id, run_id, created_by=getattr(ctx, "user_id", None)
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"suggestions": [_suggestion_to_dict(s) for s in suggestions]}


@router.get("/suggestions", summary="Listar sugerencias gobernadas")
async def list_suggestions(
    request: Request,
    status: str | None = None,
    run_id: UUID | None = None,
) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_curator_repo
    from src.core.domain.curator import SuggestionStatus
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    parsed_status = None
    if status is not None:
        try:
            parsed_status = SuggestionStatus(status)
        except ValueError as exc:
            raise HTTPException(422, f"invalid suggestion status '{status}'") from exc
    suggestions = await get_curator_repo().list(
        ctx.organization_id, status=parsed_status, run_id=run_id
    )
    return {"suggestions": [_suggestion_to_dict(s) for s in suggestions]}


@router.post(
    "/suggestions/{suggestion_id}/decide",
    summary="Aprobar/rechazar una sugerencia (revisión humana)",
)
async def decide_suggestion(
    suggestion_id: UUID, body: SuggestionDecisionRequest, request: Request
) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_curator_repo
    from src.core.domain.curator import SuggestionStatus
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    decided_by = getattr(ctx, "user_id", None)
    if decided_by is None:
        raise HTTPException(
            409, "human reviewer required: authenticated user_id missing"
        )
    target = (
        SuggestionStatus.APPROVED
        if body.decision == "approve"
        else SuggestionStatus.REJECTED
    )
    updated = await get_curator_repo().decide(
        ctx.organization_id,
        suggestion_id,
        status=target,
        decided_by=decided_by,
        reason=body.reason,
    )
    if updated is None:
        raise HTTPException(404, "Suggestion not found")
    return {"suggestion": _suggestion_to_dict(updated)}


@router.post(
    "/shadow", status_code=201, summary="Comparar baseline vs cognitive (fase 8)"
)
async def run_shadow_comparison(body: ShadowRunRequest, request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_shadow_evaluator
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    scope = await _resolve_scope(request, ctx)
    comparison = await get_shadow_evaluator().evaluate(
        organization_id=ctx.organization_id, query=body.query, scope=scope
    )
    return {"comparison": comparison.to_dict()}


@router.get("/shadow", summary="Listar comparaciones shadow")
async def list_shadow_comparisons(request: Request) -> dict:
    _require_cognitive_enabled()
    from src.api.deps import get_shadow_repo
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    comparisons = await get_shadow_repo().list(ctx.organization_id)
    return {"comparisons": [c.to_dict() for c in comparisons]}


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

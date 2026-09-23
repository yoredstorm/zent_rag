# =============================================================================
# Company Discovery API — tenant scoped, paginada.
# Candidatos, validación, promoción, jobs, gaps, conflictos y compilación de
# contexto empresarial. Nada se confirma sin derecho explícito.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.core.domain.company_discovery import (
    CandidateKind,
    DiscoverySourceKind,
    DiscoveryStage,
    DiscoveryTrigger,
)
from src.platform.rbac.policy import require_permission

router = APIRouter(prefix="/api/v1/company-discovery", tags=["CompanyDiscovery"])


def _engine():
    from src.company.wiring import company_discovery_engine

    return company_discovery_engine()


def _store():
    from src.company.wiring import company_discovery_repository

    return company_discovery_repository()


def _compiler():
    from src.company.wiring import company_context_compiler

    return company_context_compiler()


def _kinds(values: list[str] | None) -> tuple[CandidateKind, ...]:
    if not values:
        return ()
    try:
        return tuple(CandidateKind(value) for value in values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_kind", "message": "Invalid candidate kind"},
        ) from exc


def _stages(values: list[str] | None) -> tuple[DiscoveryStage, ...]:
    if not values:
        return ()
    try:
        return tuple(DiscoveryStage(value) for value in values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_stage", "message": "Invalid stage"},
        ) from exc


def _source_kinds(values: list[str] | None) -> tuple[DiscoverySourceKind, ...]:
    if not values:
        return ()
    try:
        return tuple(DiscoverySourceKind(value) for value in values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_source_kind",
                "message": "Invalid discovery source kind",
            },
        ) from exc


def _candidate_view(candidate) -> dict:
    return candidate.to_dict()


class RunDiscoveryIn(BaseModel):
    model_config = {"extra": "forbid"}

    source_kinds: list[str] = Field(default_factory=list, max_length=20)
    run_now: bool = Field(
        default=False,
        description="Ejecuta la corrida en este request (bloqueante). Por defecto se encola.",
    )


class CompileContextIn(BaseModel):
    model_config = {"extra": "forbid"}

    request: str = Field(min_length=1, max_length=2000)
    task: str = Field(default="", max_length=500)
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    max_concepts: int | None = Field(default=None, ge=0, le=50)
    max_processes: int | None = Field(default=None, ge=0, le=50)
    max_relationships: int | None = Field(default=None, ge=0, le=200)
    max_tokens_estimate: int | None = Field(default=None, ge=0, le=20000)


# ---------------------------------------------------------------------------
# Candidatos
# ---------------------------------------------------------------------------


@router.get("/candidates", summary="Candidatos descubiertos")
async def list_candidates(
    request: Request,
    kind: list[str] | None = Query(default=None),
    stage: list[str] | None = Query(default=None),
    source_kind: list[str] | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    store = _store()
    kinds = _kinds(kind)
    stages = _stages(stage)
    rows = await store.find_candidates(
        ctx.organization_id,
        kinds=kinds,
        stages=stages,
        source_kinds=_source_kinds(source_kind),
        min_confidence=min_confidence,
        query=q,
        limit=limit,
        offset=offset,
    )
    total = await store.count_candidates(
        ctx.organization_id, kinds=kinds, stages=stages
    )
    return {
        "items": [_candidate_view(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/candidates/{candidate_id}", summary="Ver un candidato")
async def get_candidate(candidate_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    candidate = await _store().get_candidate(ctx.organization_id, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"error_code": "not_found"})
    return _candidate_view(candidate)


@router.post(
    "/candidates/{candidate_id}/validate",
    summary="Validar un candidato (paso previo a confirmar)",
)
async def validate_candidate(candidate_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:write")
    try:
        candidate = await _engine().validate(
            ctx.organization_id, candidate_id, actor_id=ctx.user_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_transition", "message": str(exc)[:240]},
        ) from exc
    return _candidate_view(candidate)


@router.post(
    "/candidates/{candidate_id}/reject",
    summary="Rechazar un candidato",
)
async def reject_candidate(candidate_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:write")
    try:
        candidate = await _engine().reject(
            ctx.organization_id, candidate_id, actor_id=ctx.user_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_transition", "message": str(exc)[:240]},
        ) from exc
    return _candidate_view(candidate)


@router.post(
    "/candidates/{candidate_id}/confirm",
    summary="Confirmar y materializar un candidato en el Company Graph",
)
async def confirm_candidate(candidate_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:write")
    is_admin = False
    checker = getattr(ctx, "is_organization_admin", None)
    if callable(checker):
        is_admin = bool(checker())
    try:
        result = await _engine().promote(
            ctx.organization_id,
            candidate_id,
            actor_id=ctx.user_id,
            is_admin=is_admin,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "cannot_promote", "message": str(exc)[:240]},
        ) from exc
    return result


@router.get("/candidates/{candidate_id}/explain", summary="Evidencia del candidato")
async def explain_candidate(candidate_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    candidate = await _store().get_candidate(ctx.organization_id, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail={"error_code": "not_found"})
    return {
        "id": str(candidate.id),
        "kind": candidate.kind.value,
        "title": candidate.title,
        "stage": candidate.stage.value,
        "confidence": candidate.confidence,
        "confidence_factors": candidate.confidence_factors,
        "support": candidate.support.to_dict(),
        "source_kind": candidate.source_kind.value,
        "source_ref": candidate.source_ref,
        "discovered_by": candidate.discovered_by,
        "resolution": candidate.resolution,
        "evidence": [item.to_dict() for item in candidate.evidence],
    }


# ---------------------------------------------------------------------------
# Gaps y conflictos
# ---------------------------------------------------------------------------


@router.get("/gaps", summary="Huecos de conocimiento detectados")
async def list_gaps(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    rows = await _store().find_candidates(
        ctx.organization_id,
        kinds=(CandidateKind.KNOWLEDGE_GAP,),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_candidate_view(row) for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/conflicts", summary="Conflictos de compañía detectados")
async def list_conflicts(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    store = _store()
    gaps = await store.find_candidates(
        ctx.organization_id,
        kinds=(CandidateKind.KNOWLEDGE_GAP,),
        limit=limit,
        offset=offset,
    )
    conflicts = [
        _candidate_view(row)
        for row in gaps
        if row.payload.get("gap_kind") == "contradictory_definition"
    ]
    entities = await store.find_candidates(
        ctx.organization_id,
        kinds=(CandidateKind.ENTITY,),
        limit=limit,
        offset=offset,
    )
    for row in entities:
        if row.resolution.get("ambiguous"):
            conflicts.append(_candidate_view(row))
    return {"items": conflicts[:limit], "limit": limit, "offset": offset}


@router.get("/stats", summary="Conteos por tipo y etapa")
async def discovery_stats(request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _store().stats(ctx.organization_id)


# ---------------------------------------------------------------------------
# Jobs de descubrimiento
# ---------------------------------------------------------------------------


@router.post("/runs", status_code=202, summary="Encolar o ejecutar descubrimiento")
async def start_run(body: RunDiscoveryIn, request: Request):
    ctx = require_permission(request, "knowledge:write")
    source_kinds = _source_kinds(body.source_kinds)
    if body.run_now:
        run = await _store().start_run(
            ctx.organization_id,
            trigger=DiscoveryTrigger.MANUAL.value,
            source_kinds=source_kinds,
        )
        result = await _engine().run(
            ctx.organization_id,
            trigger=DiscoveryTrigger.MANUAL,
            source_kinds=source_kinds,
            run=run,
        )
        return result.to_dict()
    from src.company.discovery.jobs import enqueue_discovery

    run_id = await enqueue_discovery(
        ctx.organization_id,
        trigger=DiscoveryTrigger.MANUAL,
        source_kinds=source_kinds,
    )
    return {"run_id": run_id, "status": "pending"}


@router.get("/runs", summary="Corridas de descubrimiento")
async def list_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    runs = await _store().list_runs(ctx.organization_id, limit=limit, offset=offset)
    return {
        "items": [run.to_dict() for run in runs],
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Contexto empresarial compilado
# ---------------------------------------------------------------------------


@router.post("/context/compile", summary="Compilar contexto empresarial acotado")
async def compile_context(body: CompileContextIn, request: Request):
    ctx = require_permission(request, "knowledge:read")
    from src.company.context import ContextBudget

    overrides = {
        key: value
        for key, value in (
            ("max_concepts", body.max_concepts),
            ("max_processes", body.max_processes),
            ("max_relationships", body.max_relationships),
            ("max_tokens_estimate", body.max_tokens_estimate),
        )
        if value is not None
    }
    try:
        budget = ContextBudget(**overrides)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_budget", "message": str(exc)},
        ) from exc
    compiled = await _compiler().compile(
        ctx.organization_id,
        body.request,
        agent_id=body.agent_id,
        workflow_id=body.workflow_id,
        task=body.task,
        budget=budget,
    )
    return compiled.to_dict()


@router.post(
    "/context/preview",
    summary="Contexto compilado en el formato de cada consumidor",
)
async def preview_context(body: CompileContextIn, request: Request):
    ctx = require_permission(request, "knowledge:read")
    compiled = await _compiler().compile(
        ctx.organization_id,
        body.request,
        agent_id=body.agent_id,
        workflow_id=body.workflow_id,
        task=body.task,
    )
    return {
        "agent_context": compiled.to_agent_context(),
        "jev_state": compiled.to_jev_state(),
        "sql_hints": compiled.to_sql_hints(),
        "workflow_section": compiled.to_workflow_section(),
        "tokens_estimate": compiled.tokens_estimate,
        "truncated": compiled.truncated,
    }

# =============================================================================
# Learning cycle API. Lectura tenant-scoped. Promoción solo admin.
# =============================================================================
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.core.domain.learning_cycle import RecommendationAction, RunSignal, WindowName
from src.learning_engine.conflicts import ClaimView
from src.learning_engine.engine import PromotionDenied
from src.learning_engine.health import knowledge_health
from src.learning_engine.store import LearningNotFound
from src.platform.rbac.policy import require_organization_admin, require_permission

router = APIRouter(prefix="/api/v1/learning/cycle", tags=["Learning Cycle"])


class SignalIn(BaseModel):
    model_config = {"extra": "forbid"}

    pattern_key: str = Field(min_length=1, max_length=80)
    intent_family: str = Field(default="", max_length=80)
    source_type: str = Field(default="", max_length=80)
    source_name: str = Field(default="", max_length=200)
    retrieval_strategy: str = Field(default="", max_length=80)
    route_label: str = Field(default="", max_length=80)
    tool_family: str = Field(default="", max_length=80)
    failure_code: str = Field(default="", max_length=80)
    success: bool | None = None
    retried: bool = False
    fallback: bool = False
    quality: float | None = Field(default=None, ge=0, le=1)
    grounding: float | None = Field(default=None, ge=0, le=1)
    task_success: float | None = Field(default=None, ge=0, le=1)
    cost: float = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    jev_capability: str = Field(default="", max_length=80)
    executed_capability: str = Field(default="", max_length=80)
    tool_sequence: list[str] = Field(default_factory=list, max_length=8)
    tool_errors: list[str] = Field(default_factory=list, max_length=8)


class SignalBatch(BaseModel):
    model_config = {"extra": "forbid"}

    signals: list[SignalIn] = Field(min_length=1, max_length=200)
    analyze: bool = False
    window: WindowName = WindowName.LAST_24H


class ResolveIn(BaseModel):
    model_config = {"extra": "forbid"}

    action: RecommendationAction


class HealthIn(BaseModel):
    model_config = {"extra": "forbid"}

    components: dict[str, float]
    notes: dict[str, str] = Field(default_factory=dict)


class ClaimIn(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str = Field(min_length=1, max_length=200)
    predicate: str = Field(min_length=1, max_length=200)
    object_value: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=200)
    authority: str | None = Field(default=None, max_length=80)
    version: int | None = Field(default=None, ge=1)


class ConflictBatch(BaseModel):
    model_config = {"extra": "forbid"}

    claims: list[ClaimIn] = Field(min_length=2, max_length=50)


class ResolveConflictIn(BaseModel):
    model_config = {"extra": "forbid"}

    chosen_claim_id: UUID
    reason: str = Field(min_length=1, max_length=500)


def _engine():
    from src.learning_engine.wiring import learning_engine

    return learning_engine()


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, LearningNotFound):
        return HTTPException(
            status_code=404,
            detail={"error_code": "not_found", "message": "Learning record not found"},
        )
    if isinstance(exc, PromotionDenied):
        return HTTPException(
            status_code=403,
            detail={"error_code": "promotion_denied", "message": str(exc)[:240]},
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=400,
            detail={"error_code": "invalid_learning_input", "message": str(exc)[:240]},
        )
    raise exc


@router.post("/signals", summary="Ingerir telemetría. El análisis pesado no corre por cada señal.")
async def ingest_signals(body: SignalBatch, request: Request):
    ctx = require_permission(request, "knowledge:write")
    signals = [
        RunSignal(
            organization_id=ctx.organization_id,
            pattern_key=item.pattern_key,
            intent_family=item.intent_family,
            source_type=item.source_type,
            source_name=item.source_name,
            retrieval_strategy=item.retrieval_strategy,
            route_label=item.route_label,
            tool_family=item.tool_family,
            failure_code=item.failure_code,
            success=item.success,
            retried=item.retried,
            fallback=item.fallback,
            quality=item.quality,
            grounding=item.grounding,
            task_success=item.task_success,
            cost=item.cost,
            latency_ms=item.latency_ms,
            jev_capability=item.jev_capability,
            executed_capability=item.executed_capability,
            tool_sequence=tuple(item.tool_sequence),
            tool_errors=tuple(item.tool_errors),
        )
        for item in body.signals
    ]
    try:
        report = await _engine().ingest(signals, analyze=body.analyze, window=body.window)
    except Exception as exc:
        raise _http(exc) from exc
    return _report(report, accepted=len(signals))


@router.post("/analyze", summary="Agregar la ventana. No muta producción.")
async def analyze(request: Request, window: WindowName = WindowName.LAST_24H):
    ctx = require_permission(request, "knowledge:write")
    try:
        report = await _engine().analyze(ctx.organization_id, window=window)
    except Exception as exc:
        raise _http(exc) from exc
    return _report(report, accepted=0)


@router.get("/findings", summary="Findings del tenant")
async def list_findings(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    rows = await _engine().list_findings(ctx.organization_id, limit=limit, offset=offset)
    return {"items": [row.to_public_dict() for row in rows], "limit": limit, "offset": offset}


@router.get("/recommendations", summary="Recomendaciones pendientes o cerradas")
async def list_recommendations(request: Request):
    ctx = require_permission(request, "knowledge:read")
    rows = await _engine().list_recommendations(ctx.organization_id)
    return {
        "items": [row.to_public_dict() for row in rows],
        "autonomous_production_mutation": False,
    }


@router.post("/recommendations/{recommendation_id}/promote", summary="Promoción manual. Exige admin.")
async def promote(recommendation_id: UUID, request: Request):
    ctx = require_organization_admin(request)
    require_permission(request, "knowledge:write")
    try:
        audit = await _engine().promote(
            ctx.organization_id,
            recommendation_id,
            actor_id=ctx.user_id,
            is_admin=True,
        )
    except Exception as exc:
        raise _http(exc) from exc
    return audit.to_public_dict()


@router.post("/recommendations/{recommendation_id}/resolve", summary="Continuar o rechazar. Admin.")
async def resolve(recommendation_id: UUID, body: ResolveIn, request: Request):
    ctx = require_organization_admin(request)
    require_permission(request, "knowledge:write")
    try:
        result = await _engine().resolve(
            ctx.organization_id,
            recommendation_id,
            body.action,
            actor_id=ctx.user_id,
            is_admin=True,
        )
    except Exception as exc:
        raise _http(exc) from exc
    return result.to_public_dict()


@router.post("/promotions/{promotion_id}/rollback", summary="Rollback auditado. Admin.")
async def rollback(promotion_id: UUID, request: Request):
    ctx = require_organization_admin(request)
    require_permission(request, "knowledge:write")
    try:
        audit = await _engine().rollback(
            ctx.organization_id,
            promotion_id,
            actor_id=ctx.user_id,
            is_admin=True,
        )
    except Exception as exc:
        raise _http(exc) from exc
    return audit.to_public_dict()


@router.get("/comparisons", summary="Comparaciones de estrategia")
async def comparisons(request: Request, kind: str | None = Query(default=None, max_length=32)):
    ctx = require_permission(request, "knowledge:read")
    rows = await _engine().list_comparisons(ctx.organization_id, kind=kind)
    return {"items": [row.to_public_dict() for row in rows]}


@router.post("/health", summary="Knowledge Health por componente. No inventa puntajes.")
async def health(body: HealthIn, request: Request):
    require_permission(request, "knowledge:read")
    try:
        report = knowledge_health(body.components, notes=body.notes)
    except ValueError as exc:
        raise _http(exc) from exc
    return report.to_public_dict()


@router.post("/conflicts", summary="Detectar claims en conflicto. No elige el documento nuevo.")
async def conflicts(body: ConflictBatch, request: Request):
    ctx = require_permission(request, "knowledge:read")
    claims = [
        ClaimView(
            organization_id=ctx.organization_id,
            subject=item.subject,
            predicate=item.predicate,
            object_value=item.object_value,
            source=item.source,
            authority=item.authority,
            version=item.version,
        )
        for item in body.claims
    ]
    return {"items": [item.to_public_dict() for item in await _engine().record_conflicts(claims)]}


@router.post("/conflicts/{conflict_id}/resolve", summary="Registrar resolución humana.")
async def resolve_stored_conflict(conflict_id: UUID, body: ResolveConflictIn, request: Request):
    ctx = require_organization_admin(request)
    require_permission(request, "knowledge:write")
    try:
        resolved = await _engine().resolve_conflict(
            ctx.organization_id,
            conflict_id,
            actor_id=ctx.user_id,
            chosen_claim_id=body.chosen_claim_id,
            reason=body.reason,
        )
    except Exception as exc:
        raise _http(exc) from exc
    return resolved.to_public_dict()


def _report(report: Any, *, accepted: int) -> dict:
    if report is None:
        return {
            "accepted": accepted,
            "findings": [],
            "hypotheses": [],
            "experiments": [],
            "autonomous_production_mutation": False,
        }
    return {
        "accepted": accepted,
        "findings": [item.to_public_dict() for item in report.findings],
        "hypotheses": [item.to_public_dict() for item in report.hypotheses],
        "experiments": [item.to_public_dict() for item in report.experiments],
        "comparisons": [item.to_public_dict() for item in report.comparisons],
        "autonomous_production_mutation": False,
    }

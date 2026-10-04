# =============================================================================
# Knowledge Nutrition — API (enrichment, acceptance, score, acciones)
# =============================================================================
# Expone lo mínimo para operar el pipeline sin UI nueva:
#   - reporte de enrichment / fingerprint
#   - acceptance: últimas corridas + probes fallidos
#   - re-evaluación sin re-ingerir
#   - nutrition score + acciones
#   - ingreso de señales de feedback -> acción
#
# Sigue los patrones existentes: require_permission + stores Postgres scoped.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.deps import get_embedding_provider, get_vector_store
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.acceptance import PostgresAcceptanceStore, evaluate_probes
from src.knowledge.acceptance.contracts import RetrievalProbe
from src.knowledge.acceptance.store import probe_from_row
from src.knowledge.nutrition import (
    FailureSignals,
    PostgresNutritionStore,
    apply_feedback_nutrition,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge Nutrition"])


class ReevaluateRequest(BaseModel):
    document_id: UUID
    max_probes: int = Field(default=50, ge=1, le=500)
    min_recall_at_5: float = Field(default=0.6, ge=0.0, le=1.0)


class FeedbackSignalsRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    retrieved_chunks: int = Field(default=0, ge=0)
    top_score: float | None = None
    evidence_used: int = Field(default=0, ge=0)
    citations: int = Field(default=0, ge=0)
    answer_gate: str | None = Field(default=None, max_length=40)
    planner_path: str | None = Field(default=None, max_length=80)
    feedback_rating: str | None = Field(default=None, max_length=10)
    feedback_reason: str | None = Field(default=None, max_length=40)
    lexical_hit: bool | None = None
    semantic_hit: bool | None = None
    wrong_source: bool | None = None
    acl_filtered: bool | None = None
    temporal_mismatch: bool | None = None
    stale: bool | None = None
    conflict: bool | None = None
    entity_unresolved: bool | None = None
    parser_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    reconstruction_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    source_id: UUID | None = None
    document_id: UUID | None = None


def _probe_from_row(row: dict) -> RetrievalProbe:
    """Compat: el converter vive en el store (reutilizado por CLI/API)."""
    return probe_from_row(row)


@router.get("/nutrition/score", summary="Nutrition score por documento")
async def nutrition_score(
    request: Request,
    document_id: UUID,
    scope: str = Query(default="document", max_length=30),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresNutritionStore()
    state = await store.get_state(
        ctx.organization_id, scope=scope, document_id=document_id
    )
    if state is None:
        raise HTTPException(status_code=404, detail="nutrition state not found")
    return state


@router.get("/nutrition/actions", summary="Acciones de nutrition")
async def nutrition_actions(
    request: Request,
    document_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresNutritionStore()
    actions = await store.list_actions(
        ctx.organization_id, document_id=document_id, status=status, limit=limit
    )
    return {"actions": actions, "count": len(actions)}


@router.get("/retrieval-acceptance", summary="Últimas evaluaciones de acceptance")
async def retrieval_acceptance(
    request: Request,
    document_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresAcceptanceStore()
    evaluations = await store.list_evaluations(
        ctx.organization_id, document_id=document_id, limit=limit
    )
    return {"evaluations": evaluations, "count": len(evaluations)}


@router.get("/retrieval-probes", summary="Probes de retrieval del documento")
async def retrieval_probes(
    request: Request,
    document_id: UUID,
    active_only: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresAcceptanceStore()
    probes = await store.list_probes(
        ctx.organization_id, document_id=document_id, active_only=active_only, limit=limit
    )
    failed = [
        row for row in probes
        if (row.get("last_result") or {}).get("passed") is False
    ]
    return {"probes": probes, "count": len(probes), "failed": failed}


@router.post("/retrieval-acceptance/reevaluate", summary="Re-evaluar retrieval sin re-ingerir")
async def reevaluate(request: Request, body: ReevaluateRequest) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    store = PostgresAcceptanceStore()
    rows = await store.list_probes(
        ctx.organization_id,
        document_id=body.document_id,
        active_only=True,
        limit=body.max_probes,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="no active probes for document")
    probes = tuple(_probe_from_row(row) for row in rows)
    role = "admin" if ctx.is_organization_admin() else "member"
    try:
        report = await evaluate_probes(
            probes,
            embedder=get_embedding_provider(),
            vector_store=get_vector_store(),
            role=role,
            user_id=ctx.user_id,
            min_recall_at_5=body.min_recall_at_5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval reevaluation failed", error=str(exc)[:250])
        raise HTTPException(status_code=502, detail="retrieval reevaluation failed") from exc
    await store.save_evaluation(report)
    await store.update_probe_results(report)
    return report.to_dict(include_outcomes=True)


@router.post("/nutrition/feedback", summary="Señales de un run -> acción de nutrition")
async def feedback_nutrition(request: Request, body: FeedbackSignalsRequest) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    signals = FailureSignals(
        query=body.query,
        retrieved_chunks=body.retrieved_chunks,
        top_score=body.top_score,
        evidence_used=body.evidence_used,
        citations=body.citations,
        answer_gate=body.answer_gate,
        planner_path=body.planner_path,
        feedback_rating=body.feedback_rating,
        feedback_reason=body.feedback_reason,
        lexical_hit=body.lexical_hit,
        semantic_hit=body.semantic_hit,
        wrong_source=body.wrong_source,
        acl_filtered=body.acl_filtered,
        temporal_mismatch=body.temporal_mismatch,
        stale=body.stale,
        conflict=body.conflict,
        entity_unresolved=body.entity_unresolved,
        parser_quality=body.parser_quality,
        reconstruction_quality=body.reconstruction_quality,
        source_id=str(body.source_id) if body.source_id else None,
        document_id=str(body.document_id) if body.document_id else None,
    )
    outcome = await apply_feedback_nutrition(signals, organization_id=ctx.organization_id)
    return outcome.to_dict()

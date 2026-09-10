# =============================================================================
# Knowledge Learning Routes — pipeline explícito de aprendizaje (FASE 33)
# =============================================================================
# Coherente con la API existente: org-scoped, 404 cross-tenant, RBAC
# (knowledge:read / knowledge:write) y eventos reales (SSE con replay durable).
#
# Endpoints FASE 33A (backend foundation):
#   GET  /status | /score | /sources | /runs | /runs/{id} | /runs/{id}/steps
#   GET  /runs/{id}/events | /runs/{id}/stream | /events | /settings
#   POST /start
#   PUT  /settings
# FASE 33B (LLM Semantic Intelligence):
#   GET  /runs/{id}/llm-analyses | /analyses
# FASE 33C (Relationship Intelligence & Knowledge Graph):
#   GET  /entities | /graph | /gaps | /rules
# FASE 33D (AI Business Questions & Human Validation):
#   GET  /questions | /questions/{id} | /feedback
#   POST /questions/{id}/answer | /skip | /defer
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text

from src.api.deps import (
    get_catalog_store,
    get_job_repo,
    get_knowledge_evaluation_service,
    get_knowledge_graph_service,
    get_knowledge_learning_engine,
    get_knowledge_learning_repo,
    get_knowledge_score_service,
    get_knowledge_validation_engine,
)
from src.catalog.store import PostgresCatalogStore
from src.core.config import get_settings
from src.core.domain.knowledge_learning import (
    DEFAULT_GATE_THRESHOLDS,
    DEFAULT_SCORE_WEIGHTS,
    KnowledgeGate,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_learning.events import (
    KnowledgeEventEmitter,
    knowledge_event_source,
)
from src.platform.knowledge_learning.models import (
    AnswerQuestionRequest,
    EvaluationRunRequest,
    LearningSettingsRequest,
    SkipQuestionRequest,
    StartLearningRequest,
)
from src.platform.knowledge_learning.repository import (
    ActiveRunExistsError,
    PostgresKnowledgeLearningRepository,
)
from src.platform.knowledge_learning.validation_engine import (
    QuestionAlreadyResolvedError,
)
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge/learning", tags=["Knowledge Learning"])


def _ctx(request: Request):
    return getattr(request.state, "tenant_context", None)


def _org(request: Request) -> UUID:
    ctx = _ctx(request)
    if ctx is None or ctx.tenant_id is None:
        raise HTTPException(401, "Tenant context required")
    return ctx.tenant_id


def _user(request: Request) -> UUID | None:
    ctx = _ctx(request)
    return ctx.user_id if ctx else None


def _ensure_enabled() -> None:
    if not get_settings().RAG_KNOWLEDGE_LEARNING_ENABLED:
        raise HTTPException(403, "Knowledge learning is disabled")


async def _audit(
    request: Request, action: str, resource_type: str, resource_id
) -> None:
    try:
        from src.infrastructure.postgres.relational_db import (
            PostgresAuditLogRepository,
        )
        from src.platform.audit.service import AuditLogService

        await AuditLogService(PostgresAuditLogRepository()).write(
            _ctx(request), action, resource_type, resource_id
        )
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------- status
@router.get("/status", summary="Estado global del aprendizaje de conocimiento")
async def learning_status(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    await repo.ensure_tables()
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    sources = await catalog_store.list_sources(org, workspace_id=ws.id)

    snapshot = await repo.org_snapshot(org)
    scores = {s["source_id"]: s for s in await repo.list_scores(org)}
    active_runs = await repo.list_active_runs(org, limit=20)
    active_by_source = {
        r["catalog_source_id"]: r for r in active_runs if r.get("catalog_source_id")
    }
    global_score = await repo.get_score(org)

    learned_sources: list[dict] = []
    for source in sources:
        score = scores.get(source["id"])
        run = active_by_source.get(source["id"])
        pending = await repo.count_pending_questions(org, source_id=UUID(source["id"]))
        learned_sources.append(
            {
                "id": source["id"],
                "connector_id": source["connector_id"],
                "engine": source.get("engine"),
                "phase": source.get("phase"),
                "last_scan_at": source.get("last_scan_at"),
                "scan_error": source.get("scan_error"),
                "gate": score["gate"] if score else KnowledgeGate.NOT_READY.value,
                "overall": score["overall"] if score else None,
                "pending_questions": pending,
                "active_run_id": run["id"] if run else None,
                "active_run_status": run["status"] if run else None,
                "active_run_progress": run["overall_progress"] if run else None,
            }
        )
    pending_questions = await repo.count_pending_questions(org)

    verified = (
        snapshot.get("entities_approved", 0)
        + snapshot.get("fields_approved", 0)
        + snapshot.get("metrics_approved", 0)
        + snapshot.get("definitions_approved", 0)
    )
    return {
        "enabled": True,
        "headline": "Zent está aprendiendo cómo funciona tu negocio.",
        "counts": {
            "sources_connected": len(sources),
            "tables_total": snapshot.get("tables_total", 0),
            "columns_total": snapshot.get("columns_total", 0),
            "entities_total": snapshot.get("entities_total", 0),
            "entities_understood": snapshot.get("entities_understood", 0),
            "fields_total": snapshot.get("fields_total", 0),
            "relationships_total": snapshot.get("relationships_total", 0),
            "relationships_confirmed": snapshot.get("relationships_confirmed", 0),
            "pending_questions": pending_questions,
            "verified_knowledge": verified,
            "open_gaps": snapshot.get("open_gaps", 0),
        },
        "readiness": {
            "overall": global_score["overall"] if global_score else None,
            "gate": global_score["gate"] if global_score else KnowledgeGate.NOT_READY.value,
            "computed_at": global_score["computed_at"] if global_score else None,
        },
        "active_runs": active_runs,
        "sources": learned_sources,
    }


# -------------------------------------------------------------------- score
@router.get("/score", summary="Knowledge Readiness con composición y razones")
async def learning_score(
    request: Request,
    source_id: UUID | None = None,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    score_service=Depends(get_knowledge_score_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    if source_id is not None:
        source = await catalog_store.get_source(org, source_id)
        if source is None:
            raise HTTPException(404, "Catalog source not found")
    result = await score_service.compute(org, source_id=source_id, persist=True)
    payload = result.to_dict()
    payload["gate_labels"] = {
        "NOT_READY": "Aún no listo",
        "LEARNING": "Aprendiendo",
        "NEEDS_INPUT": "Necesita tu ayuda",
        "READY": "Listo",
        "DEGRADED": "Degradado",
    }
    return payload


# ------------------------------------------------------------------ sources
@router.get("/sources", summary="Estado de aprendizaje por Data Source")
async def learning_sources(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> list[dict]:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    await repo.ensure_tables()
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    sources = await catalog_store.list_sources(org, workspace_id=ws.id)
    scores = {s["source_id"]: s for s in await repo.list_scores(org)}
    active_runs = await repo.list_active_runs(org, limit=50)
    active_by_source = {
        r["catalog_source_id"]: r for r in active_runs if r.get("catalog_source_id")
    }

    out: list[dict] = []
    for source in sources:
        snapshot = await repo.source_snapshot(org, UUID(source["id"]))
        score = scores.get(source["id"])
        run = active_by_source.get(source["id"])
        pending_questions = await repo.count_pending_questions(
            org, source_id=UUID(source["id"])
        )
        tables_total = snapshot.get("tables_total", 0)
        columns_total = snapshot.get("columns_total", 0)
        fields_total = snapshot.get("fields_total", 0)
        phase = source.get("phase")
        connectivity = (
            "healthy"
            if phase in ("COMPLETED", "WAITING_REVIEW") and not source.get("scan_error")
            else ("degraded" if phase in ("PARTIAL", "FAILED") else "unknown")
        )
        out.append(
            {
                "source_id": source["id"],
                "connector_id": source["connector_id"],
                "engine": source.get("engine"),
                "connectivity": connectivity,
                "phase": phase,
                "last_learning_at": source.get("last_scan_at"),
                "scan_error": source.get("scan_error"),
                "knowledge": {
                    "overall": score["overall"] if score else None,
                    "gate": score["gate"] if score else KnowledgeGate.NOT_READY.value,
                },
                "tables": {
                    "analyzed": snapshot.get("tables_analyzed", 0),
                    "total": tables_total,
                },
                "fields": {
                    "understood": fields_total,
                    "total": columns_total,
                    "documented": snapshot.get("columns_documented", 0),
                },
                "relationships": {
                    "discovered": snapshot.get("relationships_total", 0),
                    "confirmed": snapshot.get("relationships_confirmed", 0),
                },
                "pending_questions": pending_questions,
                "active_run": (
                    {
                        "id": run["id"],
                        "status": run["status"],
                        "current_stage": run["current_stage"],
                        "overall_progress": run["overall_progress"],
                    }
                    if run
                    else None
                ),
            }
        )
    return out


# --------------------------------------------------- entities / graph / gaps
@router.get("/entities", summary="What Zent Learned: entidades entendidas")
async def learning_entities(
    request: Request,
    source_id: UUID | None = None,
    limit: int = 100,
    graph_service=Depends(get_knowledge_graph_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    entities = await graph_service.learned_entities(
        _org(request), source_id=source_id, limit=limit
    )
    return {"entities": entities, "count": len(entities)}


@router.get("/graph", summary="Knowledge Map (nodos y aristas del negocio)")
async def learning_graph(
    request: Request,
    source_id: UUID | None = None,
    node_types: str | None = None,
    q: str | None = None,
    limit_nodes: int = 300,
    limit_edges: int = 600,
    graph_service=Depends(get_knowledge_graph_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    if not get_settings().RAG_KNOWLEDGE_GRAPH_ENABLED:
        raise HTTPException(403, "Knowledge graph is disabled")
    parsed_types = None
    if node_types:
        valid = {
            "datasource",
            "entity",
            "field",
            "metric",
            "dimension",
            "rule",
            "synonym",
            "verified_question",
        }
        parsed_types = {t.strip().lower() for t in node_types.split(",") if t.strip()}
        unknown = parsed_types - valid
        if unknown:
            raise HTTPException(400, f"node_types inválidos: {sorted(unknown)}")
    return await graph_service.build(
        _org(request),
        source_id=source_id,
        node_types=parsed_types,
        q=(q or "").strip() or None,
        limit_nodes=min(max(limit_nodes, 1), 2000),
        limit_edges=min(max(limit_edges, 1), 4000),
    )


@router.get("/gaps", summary="Knowledge gaps accionables")
async def learning_gaps(
    request: Request,
    source_id: UUID | None = None,
    limit: int = 200,
    graph_service=Depends(get_knowledge_graph_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    return await graph_service.gaps(_org(request), source_id=source_id, limit=limit)


@router.get("/rules", summary="Reglas de negocio aprendidas")
async def learning_rules(
    request: Request,
    provenance: str | None = None,
    limit: int = 200,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    rules = await repo.list_business_rules(
        _org(request), provenance=provenance, limit=limit
    )
    return {"rules": rules, "count": len(rules)}


# ------------------------------------------------------------ evaluation (33G)
@router.get("/evaluation", summary="Última auto-evaluación RAG del conocimiento")
async def get_learning_evaluation(
    request: Request,
    source_id: UUID | None = None,
    service=Depends(get_knowledge_evaluation_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    settings = get_settings()
    latest = await service.latest(_org(request), source_id)
    return {
        "enabled": settings.RAG_KNOWLEDGE_EVALUATION_ENABLED,
        "judge_enabled": settings.RAG_KNOWLEDGE_EVALUATION_JUDGE,
        "max_questions": settings.RAG_KNOWLEDGE_EVALUATION_MAX_QUESTIONS,
        "latest": latest,
    }


@router.post(
    "/evaluation/run",
    summary="Zent se examina: auto-evaluación RAG con preguntas sintéticas",
)
async def run_learning_evaluation(
    body: EvaluationRunRequest,
    request: Request,
    service=Depends(get_knowledge_evaluation_service),
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    org = _org(request)
    source = await catalog_store.get_source(org, body.source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    result = await service.run(org, source_id=body.source_id)
    await _audit(request, "knowledge.evaluation_run", "learning_evaluation", body.source_id)
    return result


# ----------------------------------------------------------------- questions
@router.get("/questions", summary="Preguntas de negocio (human-in-the-loop)")
async def list_learning_questions(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    status: str | None = None,
    priority: str | None = None,
    source_id: UUID | None = None,
    run_id: UUID | None = None,
    entity_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    valid_status = {"pending", "answered", "skipped", "deferred", "expired"}
    if status and status not in valid_status:
        raise HTTPException(400, f"status debe ser uno de {sorted(valid_status)}")
    valid_priority = {"critical", "high", "medium", "low"}
    if priority and priority not in valid_priority:
        raise HTTPException(400, f"priority debe ser uno de {sorted(valid_priority)}")
    questions = await repo.list_questions(
        org,
        status=status,
        priority=priority,
        source_id=source_id,
        run_id=run_id,
        entity_id=entity_id,
        limit=limit,
        offset=offset,
    )
    pending = await repo.count_pending_questions(
        org, source_id=source_id, run_id=run_id
    )
    blocking = await repo.count_pending_questions(
        org,
        source_id=source_id,
        run_id=run_id,
        priorities=["critical", "high"],
    )
    return {
        "questions": questions,
        "count": len(questions),
        "pending": pending,
        "blocking": blocking,
    }


@router.get("/questions/{question_id}", summary="Detalle de una pregunta")
async def get_learning_question(
    question_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    question = await repo.get_question(_org(request), question_id)
    if question is None:
        raise HTTPException(404, "Question not found")
    return question


@router.post(
    "/questions/{question_id}/answer",
    summary="Responde y propaga el conocimiento",
)
async def answer_learning_question(
    question_id: UUID,
    body: AnswerQuestionRequest,
    request: Request,
    engine=Depends(get_knowledge_validation_engine),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    structured = dict(body.structured_answer or {})
    if body.choice and "choice" not in structured:
        structured["choice"] = body.choice
    try:
        result = await engine.answer(
            _org(request),
            question_id,
            answer_text=body.answer or body.choice or "",
            structured_answer=structured,
            answered_by=_user(request),
        )
    except QuestionAlreadyResolvedError as exc:
        raise HTTPException(
            409,
            {
                "error_code": "question_already_resolved",
                "message": f"La pregunta ya está en estado {exc}.",
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "Question not found")
    await _audit(
        request, "knowledge.question_answered", "knowledge_question", question_id
    )
    return result


@router.post("/questions/{question_id}/skip", summary="Descarta una pregunta")
async def skip_learning_question(
    question_id: UUID,
    body: SkipQuestionRequest,
    request: Request,
    engine=Depends(get_knowledge_validation_engine),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    try:
        result = await engine.skip(
            _org(request),
            question_id,
            reason=body.reason,
            acted_by=_user(request),
        )
    except QuestionAlreadyResolvedError as exc:
        raise HTTPException(
            409,
            {
                "error_code": "question_already_resolved",
                "message": f"La pregunta ya está en estado {exc}.",
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "Question not found")
    await _audit(request, "knowledge.question_skipped", "knowledge_question", question_id)
    return result


@router.post("/questions/{question_id}/defer", summary="Responder más tarde")
async def defer_learning_question(
    question_id: UUID,
    body: SkipQuestionRequest,
    request: Request,
    engine=Depends(get_knowledge_validation_engine),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    try:
        result = await engine.defer(
            _org(request),
            question_id,
            reason=body.reason,
            acted_by=_user(request),
        )
    except QuestionAlreadyResolvedError as exc:
        raise HTTPException(
            409,
            {
                "error_code": "question_already_resolved",
                "message": f"La pregunta ya está en estado {exc}.",
            },
        ) from exc
    if result is None:
        raise HTTPException(404, "Question not found")
    await _audit(request, "knowledge.question_deferred", "knowledge_question", question_id)
    return result


@router.get("/feedback", summary="Feedback humano aplicado al conocimiento")
async def list_learning_feedback(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    run_id: UUID | None = None,
    source_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    feedback = await repo.list_feedback(
        _org(request),
        run_id=run_id,
        source_id=source_id,
        limit=limit,
        offset=offset,
    )
    return {"feedback": feedback, "count": len(feedback)}


# --------------------------------------------------------------------- runs
@router.get("/runs", summary="Lista de runs de aprendizaje")
async def list_learning_runs(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    catalog_source_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    runs = await repo.list_runs(
        _org(request),
        catalog_source_id=catalog_source_id,
        status=status,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return {"runs": runs, "count": len(runs)}


@router.post("/runs/{run_id}/cancel", summary="Cancela un run activo")
async def cancel_learning_run(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    job_repo=Depends(get_job_repo),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    org = _org(request)
    run = await repo.get_run(org, run_id)
    if run is None:
        raise HTTPException(404, "Learning run not found")
    if run["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            409,
            {
                "error_code": "learning_run_not_active",
                "message": f"El run ya está en estado {run['status']}.",
            },
        )
    await repo.update_run(
        org,
        run_id,
        status="cancelled",
        current_stage=run.get("current_stage") or "connecting",
        finished_at=datetime.now(timezone.utc),
    )
    # Marca el job durable como cancelado si aún no terminó.
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM ingestion_jobs "
                    "WHERE organization_id = :oid "
                    "AND cursor_snapshot->>'run_id' = :rid "
                    "AND status IN ('pending','running')"
                ),
                {"oid": org, "rid": str(run_id)},
            )
        ).fetchall()
    finally:
        await session.close()
    for row in rows:
        job_id = row[0] if isinstance(row, tuple) else row.id
        await job_repo.update_job(
            UUID(str(job_id)),
            status="canceled",
            retry_at=None,
            completed_at=datetime.now(timezone.utc),
            error_summary={"cancelled": True},
        )
    try:
        await KnowledgeEventEmitter(repo).emit(
            organization_id=org,
            event_type="learning.cancelled",
            message="Aprendizaje cancelado por el usuario.",
            run_id=run_id,
            source_id=(
                UUID(run["catalog_source_id"])
                if run.get("catalog_source_id")
                else None
            ),
            severity="warning",
            payload={"stage": run.get("current_stage")},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cancel event emit failed", error=str(exc)[:200])
    try:
        from src.infrastructure.observability.metrics import (
            knowledge_learning_runs_total,
        )

        knowledge_learning_runs_total.labels(
            organization_id=str(org),
            trigger=run.get("trigger") or "manual",
            status="cancelled",
        ).inc()
    except Exception:  # noqa: BLE001
        pass
    await _audit(request, "knowledge.learning_cancelled", "learning_run", run_id)
    return {"cancelled": str(run_id)}


@router.get("/runs/{run_id}", summary="Detalle de un run con sus etapas")
async def get_learning_run(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    run = await repo.get_run(org, run_id)
    if run is None:
        raise HTTPException(404, "Learning run not found")
    run["steps"] = await repo.list_steps(org, run_id)
    return run


@router.get("/runs/{run_id}/steps", summary="Etapas reales del run")
async def get_learning_run_steps(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> list[dict]:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    if await repo.get_run(org, run_id) is None:
        raise HTTPException(404, "Learning run not found")
    return await repo.list_steps(org, run_id)


@router.get("/runs/{run_id}/events", summary="Eventos durables de un run")
async def get_learning_run_events(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    since_seq: int = 0,
    limit: int = 200,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    if await repo.get_run(org, run_id) is None:
        raise HTTPException(404, "Learning run not found")
    events = await repo.list_events(
        org, run_id=run_id, since_seq=since_seq, limit=min(max(limit, 1), 1000)
    )
    return {"events": events, "count": len(events)}


@router.get("/events", summary="Activity feed de conocimiento (filtrable)")
async def list_learning_events(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    run_id: UUID | None = None,
    source_id: UUID | None = None,
    category: str | None = None,
    since_seq: int = 0,
    limit: int = 200,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    valid = {"discovery", "ai", "validation", "indexing", "system"}
    if category and category not in valid:
        raise HTTPException(400, f"category debe ser una de {sorted(valid)}")
    events = await repo.list_events(
        _org(request),
        run_id=run_id,
        source_id=source_id,
        category=category,
        since_seq=since_seq,
        limit=min(max(limit, 1), 1000),
    )
    return {"events": events, "count": len(events)}


@router.get(
    "/runs/{run_id}/llm-analyses",
    summary="Análisis LLM por tabla (transparencia de metadata enviada)",
)
async def get_learning_run_llm_analyses(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    limit: int = 200,
    include_result: bool = True,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    if await repo.get_run(org, run_id) is None:
        raise HTTPException(404, "Learning run not found")
    analyses = await repo.list_llm_analyses(
        org, run_id=run_id, limit=min(max(limit, 1), 500)
    )
    if not include_result:
        for item in analyses:
            item.pop("result", None)
    return {"analyses": analyses, "count": len(analyses)}


@router.get("/analyses", summary="Análisis LLM por fuente (auditoría)")
async def list_learning_llm_analyses(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    source_id: UUID | None = None,
    limit: int = 100,
    include_result: bool = False,
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    analyses = await repo.list_llm_analyses(
        _org(request),
        source_id=source_id,
        limit=min(max(limit, 1), 500),
    )
    if not include_result:
        for item in analyses:
            item.pop("result", None)
    return {"analyses": analyses, "count": len(analyses)}


@router.get(
    "/runs/{run_id}/stream",
    summary="Progreso live del run (SSE con replay durable)",
)
async def stream_learning_run(
    run_id: UUID,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
    since_seq: int = 0,
):
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    org = _org(request)
    if await repo.get_run(org, run_id) is None:
        raise HTTPException(404, "Learning run not found")
    return StreamingResponse(
        knowledge_event_source(
            org, run_id=run_id, since_seq=since_seq, repository=repo
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------- start
@router.post("/start", status_code=201, summary="Inicia el aprendizaje de una fuente")
async def start_learning(
    body: StartLearningRequest,
    request: Request,
    engine=Depends(get_knowledge_learning_engine),
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    org = _org(request)
    from src.platform.workspaces.context import resolve_workspace

    source = await catalog_store.get_source(org, body.catalog_source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    ws = await resolve_workspace(request)
    try:
        result = await engine.start_run(
            org,
            catalog_source_id=body.catalog_source_id,
            workspace_id=ws.id,
            kb_source_id=(
                UUID(source["kb_source_id"]) if source.get("kb_source_id") else None
            ),
            trigger=body.trigger,
            created_by=_user(request),
        )
    except ValueError as exc:
        if "catalog_source_not_found" in str(exc):
            raise HTTPException(404, "Catalog source not found") from exc
        raise HTTPException(400, str(exc)) from exc
    except ActiveRunExistsError:
        active = await repo.find_active_run(org, body.catalog_source_id)
        raise HTTPException(
            409,
            {
                "error_code": "learning_run_active",
                "message": "Ya hay un aprendizaje en curso para esta fuente.",
                "run": active,
            },
        )
    await _audit(request, "knowledge.learning_started", "learning_run", result["run"]["id"])
    return result


# ------------------------------------------------------------------ settings
@router.get("/settings", summary="Configuración de readiness por tenant")
async def get_learning_settings(
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    stored = await repo.get_settings(_org(request))
    return {
        "weights": {**DEFAULT_SCORE_WEIGHTS, **((stored or {}).get("weights") or {})},
        "thresholds": {
            **DEFAULT_GATE_THRESHOLDS,
            **((stored or {}).get("thresholds") or {}),
        },
        "customized": stored is not None,
        "updated_at": (stored or {}).get("updated_at"),
    }


@router.put("/settings", summary="Configura pesos y umbrales de readiness")
async def put_learning_settings(
    body: LearningSettingsRequest,
    request: Request,
    repo: PostgresKnowledgeLearningRepository = Depends(get_knowledge_learning_repo),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    org = _org(request)
    if body.weights is None and body.thresholds is None:
        raise HTTPException(400, "weights o thresholds requeridos")
    stored = await repo.upsert_settings(
        org,
        weights=body.weights,
        thresholds=body.thresholds,
        updated_by=_user(request),
    )
    await _audit(request, "knowledge.settings_updated", "knowledge_settings", org)
    return {
        "weights": {**DEFAULT_SCORE_WEIGHTS, **stored["weights"]},
        "thresholds": {**DEFAULT_GATE_THRESHOLDS, **stored["thresholds"]},
        "customized": True,
        "updated_at": stored["updated_at"],
    }

# =============================================================================
# Learning Routes — Context Advisor, Gaps, Improvements, Clustering, Replay,
# Spider (FASE 25)
# =============================================================================
# Permisos reusados: catalog:read / catalog:write. Org-scoped estricto.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import (
    get_context_advisor,
    get_intelligence_store,
    get_learning_analytics,
    get_learning_store,
    get_replay_engine,
    get_spider_service,
)
from src.infrastructure.observability.logging_config import get_logger
from src.learning.improvements import ImprovementQueue
from src.learning.store import PostgresLearningStore
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/learning", tags=["Learning"])

_VALID_STATUSES = {"OPEN", "IN_REVIEW", "RESOLVED", "DISMISSED", "BLOCKED"}
_VALID_PRIORITIES = {"critical", "high", "medium", "low"}


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


# ----------------------------------------------------------------------- gaps
@router.get("/gaps", summary="Gaps de contexto estructurados")
async def list_gaps(
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
    gap_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await intelligence_store.list_gaps(
        _org(request), gap_type=gap_type, status=status, limit=limit, offset=offset
    )


@router.post("/gaps/{gap_id}/resolve", summary="Resuelve un gap")
async def resolve_gap(
    gap_id: UUID,
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    ok = await intelligence_store.resolve_gap(org, gap_id, resolved_by=_user(request))
    if not ok:
        raise HTTPException(404, "Gap not found")
    from src.infrastructure.observability.metrics import (
        rag_context_gaps_resolved_total,
    )

    rag_context_gaps_resolved_total.labels(organization_id=str(org)).inc()
    await _audit(request, "gap.resolved", "gap", gap_id)
    return {"resolved": str(gap_id)}


# -------------------------------------------------------------------- advisor
@router.get("/advisor", summary="Context Advisor: recomendaciones accionables")
async def advisor(
    request: Request,
    question: str,
    advisor=Depends(get_context_advisor),
    intelligence_store=Depends(get_intelligence_store),
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    gap_type: str | None = None,
    concept: str | None = None,
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    gap: dict | None = None
    if concept or gap_type:
        gaps = await intelligence_store.list_gaps(org, gap_type=gap_type, limit=100)
        for g in gaps:
            if concept and g["concept"] == concept.lower():
                gap = g
                break
        if gap is None and concept:
            gap = {"gap_type": gap_type or "", "concept": concept, "impact": {}}
    return await advisor.advise(org, question, gap=gap)


# ------------------------------------------------------------- improvements
class ImprovementStatusBody(BaseModel):
    status: str
    owner: str | None = Field(default=None, max_length=120)
    priority: str | None = Field(default=None, max_length=12)


@router.get("/improvements", summary="Backlog de mejoras de inteligencia")
async def list_improvements(
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    status: str | None = None,
    gap_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await learning_store.list_improvements(
        _org(request), status=status, gap_type=gap_type, limit=limit, offset=offset
    )


@router.post("/improvements/{item_id}/status", summary="Transición de estado")
async def set_improvement_status(
    item_id: UUID,
    body: ImprovementStatusBody,
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"status debe ser uno de {sorted(_VALID_STATUSES)}")
    if body.priority and body.priority not in _VALID_PRIORITIES:
        raise HTTPException(400, f"priority debe ser uno de {sorted(_VALID_PRIORITIES)}")
    ok = await learning_store.update_improvement_status(
        org,
        item_id,
        status=body.status,
        owner=body.owner,
        priority=body.priority,
        resolved_by=_user(request),
    )
    if not ok:
        raise HTTPException(404, "Improvement not found")
    await _audit(request, "improvement.status_changed", "improvement", item_id)
    return await learning_store.get_improvement(org, item_id) or {}


# ------------------------------------------------------------------ clusters
@router.get("/clusters", summary="Clusters de preguntas no contestadas")
async def clusters(
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    days: int = 30,
) -> list[dict]:
    require_permission(request, "catalog:read")
    org = _org(request)
    questions = await _unanswered_questions(org, intelligence_store, days)
    from src.core.config import get_settings
    from src.learning.clustering import UnansweredClusterer

    queue = ImprovementQueue(learning_store)
    clusterer = UnansweredClusterer(
        queue,
        threshold=get_settings().RAG_LEARNING_CLUSTER_THRESHOLD,
        min_size=get_settings().RAG_LEARNING_CLUSTER_MIN_SIZE,
    )
    return await clusterer.run(org, questions)


async def _unanswered_questions(org: UUID, intelligence_store, days: int) -> list[dict]:
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT query_id, user_query, created_at FROM intelligence_traces "
                    "WHERE organization_id = :oid AND status <> 'ANSWERABLE' "
                    "AND created_at >= now() - make_interval(days => :days) "
                    "ORDER BY created_at DESC LIMIT 500"
                ),
                {"oid": org, "days": days},
            )
        ).fetchall()
        return [
            {
                "question": str(r.user_query or ""),
                "query_id": str(r.query_id) if r.query_id else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
            if r.user_query
        ]
    finally:
        await session.close()


@router.get("/patterns", summary="Consultas exitosas repetidas (patrones SQL)")
async def patterns(
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    days: int = 30,
) -> list[dict]:
    require_permission(request, "catalog:read")
    from src.core.config import get_settings
    from src.learning.patterns import SqlPatternDetector

    queue = ImprovementQueue(learning_store)
    detector = SqlPatternDetector(
        queue, min_queries=get_settings().RAG_LEARNING_PATTERN_MIN_QUERIES
    )
    return await detector.run(_org(request), days=days)


# -------------------------------------------------------------------- replay
class ReplayBody(BaseModel):
    knowledge_type: str = Field(min_length=1, max_length=30)
    knowledge_id: str = Field(min_length=1, max_length=64)


@router.post("/replay", status_code=201, summary="Evaluation Replay (manual)")
async def start_replay(
    body: ReplayBody,
    request: Request,
    replay_engine=Depends(get_replay_engine),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    replay_id = await replay_engine.start(
        organization_id=org,
        knowledge_type=body.knowledge_type,
        knowledge_id=body.knowledge_id,
        trigger="manual",
    )
    if replay_id is None:
        raise HTTPException(500, "Replay could not be started")
    await _audit(request, "learning.replay_started", "replay", replay_id)
    return {"replay_id": str(replay_id)}


@router.get("/replays", summary="Evaluation Replays (before/after)")
async def list_replays(
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    knowledge_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await learning_store.list_replays(
        _org(request), knowledge_type=knowledge_type, limit=limit, offset=offset
    )


# ------------------------------------------------------------------ analytics
@router.get("/analytics", summary="Tendencias del ciclo de aprendizaje")
async def analytics(
    request: Request,
    analytics_service=Depends(get_learning_analytics),
    days: int = 30,
) -> dict:
    require_permission(request, "catalog:read")
    return await analytics_service.trends(_org(request), days=days)


@router.get("/improvements/summary", summary="Continuous Improvement (mensual)")
async def improvements_summary(
    request: Request,
    analytics_service=Depends(get_learning_analytics),
) -> dict:
    require_permission(request, "catalog:read")
    return await analytics_service.monthly_summary(_org(request))


# -------------------------------------------------------------------- spider
class SpiderPolicyBody(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    enabled: bool = True
    schedule_hours: int = Field(default=24, ge=1, le=720)
    allowed_source_ids: list[str] = Field(default_factory=list)
    allowed_schemas: list[str] = Field(default_factory=list)
    excluded_objects: list[str] = Field(default_factory=list)
    profiling_level: str = "standard"
    max_cost: int = Field(default=500, ge=10, le=100_000)
    max_duration_min: int = Field(default=60, ge=1, le=1440)
    sampling_policy: str = "conservative"
    pii_policy: str = "never"


@router.get("/spider/policies", summary="Políticas del Zent Spider")
async def list_spider_policies(
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await learning_store.list_spider_policies(_org(request))


@router.post("/spider/policies", status_code=201, summary="Crea/actualiza política")
async def upsert_spider_policy(
    body: SpiderPolicyBody,
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    if body.profiling_level not in ("none", "standard", "deep"):
        raise HTTPException(400, "profiling_level inválido")
    if body.sampling_policy not in ("none", "conservative", "standard"):
        raise HTTPException(400, "sampling_policy inválido")
    if body.pii_policy not in ("never", "mask"):
        raise HTTPException(400, "pii_policy inválido")
    from src.core.domain.learning import SpiderPolicy

    policy = SpiderPolicy(
        organization_id=org,
        name=body.name,
        enabled=body.enabled,
        schedule_hours=body.schedule_hours,
        allowed_source_ids=body.allowed_source_ids,
        allowed_schemas=body.allowed_schemas,
        excluded_objects=body.excluded_objects,
        profiling_level=body.profiling_level,
        max_cost=body.max_cost,
        max_duration_min=body.max_duration_min,
        sampling_policy=body.sampling_policy,
        pii_policy=body.pii_policy,
        created_by=_user(request),
    )
    policy_id = await learning_store.upsert_spider_policy(policy)
    await _audit(request, "spider.policy_configured", "spider_policy", policy_id)
    saved = next(
        (p for p in await learning_store.list_spider_policies(org) if p["id"] == str(policy_id)),
        {},
    )
    return {"id": str(policy_id), **saved}


@router.post("/spider/policies/{policy_id}/run", summary="Ejecuta la política")
async def run_spider_policy(
    policy_id: UUID,
    request: Request,
    spider_service=Depends(get_spider_service),
    learning_store: PostgresLearningStore = Depends(get_learning_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    policies = await learning_store.list_spider_policies(org)
    if not any(p["id"] == str(policy_id) for p in policies):
        raise HTTPException(404, "Spider policy not found")
    run_id = await spider_service.start_policy_run(org, policy_id)
    await _audit(request, "spider.scan_started", "spider_run", run_id)
    return {"run_id": str(run_id) if run_id else None}


@router.get("/spider/runs", summary="Ejecuciones del Zent Spider")
async def list_spider_runs(
    request: Request,
    learning_store: PostgresLearningStore = Depends(get_learning_store),
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await learning_store.list_spider_runs(
        _org(request), limit=limit, offset=offset
    )


async def _audit(request: Request, action: str, resource_type: str, resource_id) -> None:
    try:
        from src.infrastructure.postgres.relational_db import (
            PostgresAuditLogRepository,
        )
        from src.platform.audit.service import AuditLogService

        await AuditLogService(PostgresAuditLogRepository()).write(
            _ctx(request),
            action,
            resource_type,
            resource_id,
        )
    except Exception:  # noqa: BLE001
        pass

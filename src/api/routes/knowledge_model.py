# =============================================================================
# Knowledge OS Routes — API domain-oriented del modelo de conocimiento (FASE 34)
# =============================================================================
# /api/v1/knowledge/overview | objects | objects/{id}/... | graph | search
# /api/v1/knowledge/health | quality | activity | gaps | conflicts | domains
# /api/v1/knowledge/model/rebuild | sources/{id}/learn
#
# Coexiste con /api/v1/knowledge/learning (pipeline) y /api/v1/knowledge/workspaces
# (corpus). Errores tipados: 503 knowledge_model_unavailable (nunca 0 inventado).
# =============================================================================
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.deps import (
    get_catalog_store,
    get_knowledge_learning_engine,
    get_knowledge_model_service,
)
from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.platform.knowledge_model.service import KnowledgeModelUnavailable
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge OS"])


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
    if not get_settings().KNOWLEDGE_MODEL_ENABLED:
        raise HTTPException(403, "Knowledge model is disabled")


def _unavailable(exc: KnowledgeModelUnavailable) -> HTTPException:
    return HTTPException(
        503,
        {
            "error_code": exc.code,
            "message": (
                "No pudimos obtener el conocimiento de tu organización. "
                "Esto NO significa que no exista: es un error de lectura."
            ),
            "detail": str(exc)[:300],
        },
    )


async def _audit(request: Request, action: str, resource_type: str, resource_id) -> None:
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


class ResolveConflictRequest(BaseModel):
    resolution: str = Field(pattern="^(chose_a|chose_b|merged|exception|delegated)$")
    resolved_value: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)


class ResolveGapRequest(BaseModel):
    status: str = Field(default="resolved", pattern="^(investigating|resolved|ignored)$")
    note: str | None = Field(default=None, max_length=2000)


class RebuildRequest(BaseModel):
    source_id: UUID | None = None


class LearnSourceRequest(BaseModel):
    trigger: str = Field(default="manual", pattern="^(manual|scheduled|onboarding)$")


# ------------------------------------------------------ compilaciones
@router.get("/compilations", summary="Trazas del Knowledge Compiler")
async def knowledge_compilations(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    document_id: UUID | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
) -> dict:
    """Cada corrida del compilador: qué fuente, qué produjo y cuánto tardó."""
    ctx = require_permission(request, "knowledge:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT id, workspace_id, source_id, document_id,
                           compilation_kind, status, units, entities,
                           entities_merged, facts, relationships, rules,
                           conflicts, evidence, duration_ms, error, metadata,
                           started_at, finished_at
                    FROM knowledge_compilations
                    WHERE organization_id = :org
                      AND (CAST(:document_id AS uuid) IS NULL
                           OR document_id = CAST(:document_id AS uuid))
                      AND (CAST(:source_id AS uuid) IS NULL
                           OR source_id = CAST(:source_id AS uuid))
                    ORDER BY started_at DESC
                    LIMIT :limit
                    """
                ),
                {
                    "org": ctx.organization_id,
                    "document_id": str(document_id) if document_id else None,
                    "source_id": str(source_id) if source_id else None,
                    "limit": limit,
                },
            )
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — tabla ausente en entornos previos
        logger.warning("knowledge_compilations read failed", error=str(exc)[:200])
        raise _unavailable(KnowledgeModelUnavailable(str(exc)[:200])) from exc
    finally:
        await session.close()

    return {
        "items": [
            {
                "id": str(row.id),
                "source_id": str(row.source_id) if row.source_id else None,
                "document_id": str(row.document_id) if row.document_id else None,
                "kind": row.compilation_kind,
                "status": row.status,
                "counts": {
                    "units": row.units,
                    "entities": row.entities,
                    "entities_merged": row.entities_merged,
                    "facts": row.facts,
                    "relationships": row.relationships,
                    "rules": row.rules,
                    "conflicts": row.conflicts,
                    "evidence": row.evidence,
                },
                "duration_ms": row.duration_ms,
                "error": row.error,
                "document_title": (row.metadata or {}).get("document_title"),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ],
        "total": len(rows),
    }


# ------------------------------------------------------------------- overview
@router.get("/overview", summary="Knowledge Command Center")
async def knowledge_overview(
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.overview(_org(request))
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/health", summary="Knowledge Health explicable por dimensión")
async def knowledge_health(
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        health = await service.health(_org(request))
        return health.to_dict()
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/quality", summary="Quality Center: problemas operables")
async def knowledge_quality(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.quality(_org(request), limit=limit)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/activity", summary="Actividad de conocimiento (objetos + eventos)")
async def knowledge_activity(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.activity(_org(request), limit=limit)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/stream", summary="Eventos de conocimiento en vivo (replay durable + SSE)")
async def knowledge_stream(
    request: Request,
    since_seq: int = Query(default=0, ge=0),
):
    """SSE tenant-scoped: replay durable de `knowledge_events` y live por bus.

    Permite que Knowledge Pulse y el feed se actualicen con eventos reales sin
    polling agresivo. Si el bus falla, el frontend cae a polling.
    """
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    from src.platform.knowledge_learning.events import knowledge_event_source

    return StreamingResponse(
        knowledge_event_source(_org(request), since_seq=since_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/domains", summary="Dominios del negocio con objetos y cobertura")
async def knowledge_domains(
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        domains = await service.domains(_org(request))
        return {"domains": domains, "count": len(domains)}
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/delta", summary="Knowledge Delta: qué cambió en una ventana")
async def knowledge_delta(
    request: Request,
    window: str = Query(default="24h", pattern="^(24h|7d|30d|custom)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    service=Depends(get_knowledge_model_service),
) -> dict:
    """Altas, enriquecimientos, conflictos y timeline de una ventana real.

    `window=custom` exige `since`. ERROR != ZERO: fallo de lectura → 503.
    """
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.delta(
            _org(request), window=window, since=since, until=until
        )
    except ValueError as exc:
        raise HTTPException(
            400,
            {
                "error_code": "knowledge_delta_invalid_window",
                "message": str(exc),
            },
        ) from exc
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


# -------------------------------------------------------------------- objetos
@router.get("/objects", summary="Explorador: objetos de conocimiento")
async def list_objects(
    request: Request,
    type: str | None = Query(default=None, description="Tipos separados por coma"),
    domain: str | None = None,
    status: str | None = None,
    source_id: UUID | None = None,
    q: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    order_by: str = Query(default="updated_at", pattern="^(updated_at|confidence|name|evidence)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.list_objects(
            _org(request),
            types=(type.split(",") if type else None),
            domain=domain,
            status=status,
            source_id=source_id,
            q=q,
            min_confidence=min_confidence,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/objects/{object_id}", summary="Detalle de un objeto de conocimiento")
async def get_object(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        detail = await service.object_detail(_org(request), object_id)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc
    if detail is None:
        raise HTTPException(
            404,
            {
                "error_code": "knowledge_object_not_found",
                "message": "El objeto de conocimiento no existe en esta organización.",
            },
        )
    return detail


@router.get("/objects/{object_id}/edges", summary="Relaciones del objeto")
async def get_object_edges(
    object_id: UUID,
    request: Request,
    limit: int = Query(default=200, ge=1, le=500),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        if await service.get_object(_org(request), object_id) is None:
            raise HTTPException(404, {"error_code": "knowledge_object_not_found"})
        return await service.object_edges(_org(request), object_id, limit=limit)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/objects/{object_id}/assertions", summary="Assertions del objeto")
async def get_object_assertions(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    assertions = await service.object_assertions(_org(request), object_id)
    return {"assertions": assertions, "count": len(assertions)}


@router.get("/objects/{object_id}/evidence", summary="Evidencia del objeto")
async def get_object_evidence(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    evidence = await service.object_evidence(_org(request), object_id)
    return {"evidence": evidence, "count": len(evidence)}


@router.get("/objects/{object_id}/lineage", summary="Lineage físico del objeto")
async def get_object_lineage(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    return await service.lineage(_org(request), object_id)


@router.get("/objects/{object_id}/impact", summary="WHAT DEPENDS ON THIS")
async def get_object_impact(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    return await service.impact(_org(request), object_id)


@router.get("/objects/{object_id}/history", summary="Historial de versiones")
async def get_object_history(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    versions = await service.object_versions(_org(request), object_id)
    return {"versions": versions, "count": len(versions)}


@router.post("/objects/{object_id}/verify", summary="Verificar objeto (humano)")
async def verify_object(
    object_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:validate")
    _ensure_enabled()
    result = await service.verify_object(_org(request), object_id, user_id=_user(request))
    if result is None:
        raise HTTPException(404, {"error_code": "knowledge_object_not_found"})
    await _audit(request, "knowledge.object_verified", "knowledge_object", object_id)
    return result


@router.post("/assertions/{assertion_id}/verify", summary="Verificar assertion (humano)")
async def verify_assertion(
    assertion_id: UUID,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:validate")
    _ensure_enabled()
    result = await service.verify_assertion(
        _org(request), assertion_id, user_id=_user(request)
    )
    if result is None:
        raise HTTPException(404, {"error_code": "knowledge_assertion_not_found"})
    await _audit(request, "knowledge.assertion_verified", "knowledge_assertion", assertion_id)
    return result


# -------------------------------------------------------------- search/graph
@router.get("/search", summary="Búsqueda global en el conocimiento")
async def search_knowledge(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.search(_org(request), q, limit=limit)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.get("/graph", summary="Grafo derivado del modelo (vecindario + expansión)")
async def knowledge_graph(
    request: Request,
    focus_id: UUID | None = None,
    depth: int = Query(default=1, ge=1, le=3),
    types: str | None = None,
    domains: str | None = None,
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    limit_nodes: int = Query(default=120, ge=1, le=400),
    limit_edges: int = Query(default=300, ge=1, le=800),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.graph(
            _org(request),
            focus_id=focus_id,
            depth=depth,
            kinds=(types.split(",") if types else None),
            domains=(domains.split(",") if domains else None),
            min_confidence=min_confidence,
            limit_nodes=limit_nodes,
            limit_edges=limit_edges,
        )
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


# --------------------------------------------------------------- gaps/conflicts
@router.get("/gaps", summary="Knowledge gaps priorizados")
async def list_gaps(
    request: Request,
    status: str | None = "open",
    gap_type: str | None = None,
    priority: str | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    try:
        return await service.gaps(
            _org(request),
            status=status,
            gap_type=gap_type,
            priority=priority,
            limit=limit,
            offset=offset,
        )
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc


@router.post("/gaps/{gap_id}/resolve", summary="Resolver/ignorar un gap")
async def resolve_gap(
    gap_id: UUID,
    body: ResolveGapRequest,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:write")
    _ensure_enabled()
    ok = await service.resolve_gap(
        _org(request),
        gap_id,
        user_id=_user(request),
        status=body.status,
        note=body.note,
    )
    if not ok:
        raise HTTPException(404, {"error_code": "knowledge_gap_not_found"})
    await _audit(request, "knowledge.gap_resolved", "knowledge_gap", gap_id)
    return {"id": str(gap_id), "status": body.status}


@router.get("/ingestion-quality", summary="Calidad de ingesta (parsing, no conocimiento)")
async def list_ingestion_quality(
    request: Request,
    status: str | None = "open",
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    return await service.ingestion_quality(
        _org(request), status=status, kind=kind, limit=limit
    )


@router.get("/conflicts", summary="Conflictos de conocimiento")
async def list_conflicts(
    request: Request,
    status: str | None = "open",
    limit: int = Query(default=100, ge=1, le=300),
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:read")
    _ensure_enabled()
    return await service.conflicts(_org(request), status=status, limit=limit)


@router.post("/conflicts/{conflict_id}/resolve", summary="Resolver conflicto (canonical)")
async def resolve_conflict(
    conflict_id: UUID,
    body: ResolveConflictRequest,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:admin")
    _ensure_enabled()
    result = await service.resolve_conflict(
        _org(request),
        conflict_id,
        resolution=body.resolution,
        resolved_value=body.resolved_value,
        user_id=_user(request),
        reason=body.reason,
    )
    if result is None:
        raise HTTPException(404, {"error_code": "knowledge_conflict_not_found"})
    await _audit(request, "knowledge.conflict_resolved", "knowledge_conflict", conflict_id)
    return result


# ------------------------------------------------------------------- acciones
@router.post("/model/rebuild", summary="Reconstruir el modelo desde las fuentes")
async def rebuild_model(
    body: RebuildRequest,
    request: Request,
    service=Depends(get_knowledge_model_service),
) -> dict:
    require_permission(request, "knowledge:admin")
    _ensure_enabled()
    try:
        result = await service.materialize(_org(request), source_id=body.source_id)
    except KnowledgeModelUnavailable as exc:
        raise _unavailable(exc) from exc
    await _audit(request, "knowledge.model_rebuilt", "knowledge_model", body.source_id)
    return result


@router.post("/sources/{source_id}/learn", status_code=201, summary="Aprender de una fuente")
async def learn_source(
    source_id: UUID,
    body: LearnSourceRequest,
    request: Request,
    engine=Depends(get_knowledge_learning_engine),
    catalog_store=Depends(get_catalog_store),
) -> dict:
    require_permission(request, "knowledge:run_learning")
    _ensure_enabled()
    org = _org(request)
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, {"error_code": "knowledge_source_not_found"})
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    try:
        result = await engine.start_run(
            org,
            catalog_source_id=source_id,
            workspace_id=ws.id,
            kb_source_id=(
                UUID(source["kb_source_id"]) if source.get("kb_source_id") else None
            ),
            trigger=body.trigger,
            created_by=_user(request),
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if "catalog_source_not_found" in message:
            raise HTTPException(404, {"error_code": "knowledge_source_not_found"}) from exc
        if message.startswith("source_not_learnable"):
            raise HTTPException(
                400,
                {
                    "error_code": "source_not_learnable",
                    "message": (
                        "Esta fuente es un archivo indexado, no una base SQL. "
                        "El aprendizaje aplica a fuentes SQL; los archivos se "
                        "consultan en Fuentes."
                    ),
                },
            ) from exc
        from src.platform.knowledge_learning.repository import ActiveRunExistsError

        if isinstance(exc, ActiveRunExistsError):
            raise HTTPException(
                409,
                {
                    "error_code": "learning_run_active",
                    "message": "Ya hay un aprendizaje en curso para esta fuente.",
                },
            ) from exc
        raise HTTPException(
            400,
            {"error_code": "learning_start_failed", "message": message[:300]},
        ) from exc
    await _audit(request, "knowledge.learning_started", "learning_run", result["run"]["id"])
    return result

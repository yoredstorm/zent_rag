# =============================================================================
# Knowledge Sessions Routes — ZENT está aprendiendo
# =============================================================================
# Expone el aprendizaje real de la ingesta:
#   POST   /api/v1/knowledge/sessions                 — abre una sesión
#   GET    /api/v1/knowledge/sessions                 — sesiones recientes
#   GET    /api/v1/knowledge/sessions/{id}            — detalle + delta
#   GET    /api/v1/knowledge/sessions/{id}/events     — stream durable (páginas)
#   GET    /api/v1/knowledge/sessions/{id}/feed       — descubrimientos agrupados
#   GET    /api/v1/knowledge/sessions/{id}/graph      — grafo de la sesión
#   GET    /api/v1/knowledge/sessions/{id}/stream     — SSE (replay + live)
#
# Ningún número es decorativo: todos salen de tablas del Knowledge OS o de los
# eventos que el Knowledge Compiler emitió al trabajar.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.api.deps import (
    get_job_repo,
    get_knowledge_session_service,
    get_source_repo,
)
from src.core.ports import IngestionJobRepository, SourceRepository
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.platform.knowledge_sessions.emitter import learning_session_event_source
from src.platform.knowledge_sessions.service import group_discoveries
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge/sessions", tags=["Knowledge Sessions"])


class StartSessionRequest(BaseModel):
    title: str = Field(default="", max_length=255)
    source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    origin: str = Field(default="manual", max_length=32)


@router.post("", status_code=201, summary="Abrir una sesión de aprendizaje")
async def start_session(
    request: Request,
    body: StartSessionRequest,
    sessions=Depends(get_knowledge_session_service),
    sources: SourceRepository = Depends(get_source_repo),
    jobs: IngestionJobRepository = Depends(get_job_repo),
) -> dict:
    ctx = require_permission(request, "sources:write")
    await sessions.ensure_tables()
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    session = await sessions.start_session(
        ctx.organization_id,
        title=body.title or "Aprendizaje de conocimiento",
        origin=body.origin,
        workspace_id=getattr(ws, "id", None),
    )
    attached = 0
    for source_id in body.source_ids:
        source = await sources.get_source(ctx.organization_id, source_id)
        if source is None:
            continue
        from src.knowledge.uploads import enqueue_source_sync

        async def _attach(job, _source=source) -> None:
            await sessions.attach_source(
                session,
                source_id=_source.id,
                job_id=job.id,
                name=_source.name,
                source_type=_source.type,
            )

        await enqueue_source_sync(ctx, jobs, source, on_created=_attach)
        attached += 1
    if attached:
        await sessions.seal_session(ctx.organization_id, session.id)
    detail = await sessions.get_session_detail(ctx.organization_id, session.id)
    return detail or {"session_id": str(session.id), "attached": attached}


@router.post(
    "/{session_id}/seal",
    summary="Cerrar la sesión: ya no se adjuntan más fuentes",
)
async def seal_session(
    session_id: str,
    request: Request,
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    """El cliente terminó de subir: el aprendizaje puede declararse completo."""
    ctx = require_permission(request, "sources:write")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    session = await sessions.get_session(ctx.organization_id, sid)
    if session is None:
        raise HTTPException(404, "Learning session not found")
    await sessions.seal_session(ctx.organization_id, sid)
    detail = await sessions.get_session_detail(ctx.organization_id, sid)
    return detail or {"session_id": str(sid)}


@router.get("", summary="Sesiones de aprendizaje recientes")
async def list_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    ctx = require_permission(request, "sources:read")
    await sessions.ensure_tables()
    items = await sessions.list_sessions(ctx.organization_id, limit=limit)
    return {"sessions": items, "count": len(items)}


@router.get("/{session_id}", summary="Detalle de una sesión de aprendizaje")
async def get_session(
    session_id: str,
    request: Request,
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    await sessions.ensure_tables()
    detail = await sessions.get_session_detail(ctx.organization_id, sid)
    if detail is None:
        raise HTTPException(404, "Learning session not found")
    return detail


@router.get("/{session_id}/events", summary="Eventos durables de la sesión")
async def list_session_events(
    session_id: str,
    request: Request,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=400, ge=1, le=2000),
    source_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None, max_length=60),
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    events = await sessions.list_events(
        ctx.organization_id,
        sid,
        since_seq=since_seq,
        source_id=source_id,
        event_type=event_type,
        limit=limit,
    )
    return {"events": events, "count": len(events)}


@router.get("/{session_id}/feed", summary="Descubrimientos agrupados")
async def session_feed(
    session_id: str,
    request: Request,
    limit: int = Query(default=60, ge=1, le=200),
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    events = await sessions.list_events(
        ctx.organization_id, sid, since_seq=0, limit=2000
    )
    return {"discoveries": group_discoveries(events, limit=limit)}


@router.get("/{session_id}/graph", summary="Grafo de la sesión (nodos relevantes)")
async def session_graph(
    session_id: str,
    request: Request,
    sessions=Depends(get_knowledge_session_service),
) -> dict:
    """Solo conceptos importantes de la sesión + sus conexiones relevantes.

    Nunca se manda el grafo completo: nodos nuevos de las fuentes de la sesión
    (máx. 120) y las aristas que los tocan (máx. 300), más los vecinos que ya
    existían en ZENT, marcados como ``known``.
    """
    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    detail = await sessions.get_session_detail(ctx.organization_id, sid)
    if detail is None:
        raise HTTPException(404, "Learning session not found")
    source_ids = [
        source["source_id"]
        for source in detail.get("sources", [])
        if source.get("source_id")
    ]
    if not source_ids:
        return {"nodes": [], "edges": [], "session_id": str(sid)}

    session = await get_async_session()
    try:
        node_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, name, display_name, kind, source_id
                    FROM knowledge_canonical_objects
                    WHERE organization_id = :org
                      AND source_id = ANY(:sources)
                    ORDER BY updated_at DESC
                    LIMIT 120
                    """
                ),
                {
                    "org": ctx.organization_id,
                    "sources": [str(value) for value in source_ids],
                },
            )
        ).fetchall()
        nodes = {
            str(row.id): {
                "id": str(row.id),
                "name": row.display_name or row.name or "",
                "kind": str(row.kind),
                "known": False,
            }
            for row in node_rows
        }
        if not nodes:
            return {"nodes": [], "edges": [], "session_id": str(sid)}
        edge_rows = (
            await session.execute(
                text(
                    """
                    SELECT e.id, e.subject_id, e.object_id, e.predicate,
                           s.name AS subject_name, o.name AS object_name,
                           s.kind AS subject_kind, o.kind AS object_kind
                    FROM knowledge_edges e
                    JOIN knowledge_canonical_objects s
                      ON s.id = e.subject_id AND s.organization_id = e.organization_id
                    JOIN knowledge_canonical_objects o
                      ON o.id = e.object_id AND o.organization_id = e.organization_id
                    WHERE e.organization_id = :org
                      AND (e.subject_id = ANY(:node_ids)
                        OR e.object_id = ANY(:node_ids))
                    ORDER BY e.updated_at DESC
                    LIMIT 300
                    """
                ),
                {
                    "org": ctx.organization_id,
                    "node_ids": [UUID(key) for key in nodes],
                },
            )
        ).fetchall()
        edges: list[dict] = []
        for row in edge_rows:
            subject_id = str(row.subject_id)
            object_id = str(row.object_id)
            for node_id, name, kind in (
                (subject_id, row.subject_name, row.subject_kind),
                (object_id, row.object_name, row.object_kind),
            ):
                if node_id not in nodes and len(nodes) < 200:
                    nodes[node_id] = {
                        "id": node_id,
                        "name": name or "",
                        "kind": str(kind),
                        "known": True,
                    }
            edges.append(
                {
                    "id": str(row.id),
                    "subject": subject_id,
                    "object": object_id,
                    "predicate": str(row.predicate),
                }
            )
        return {
            "session_id": str(sid),
            "nodes": list(nodes.values()),
            "edges": edges,
        }
    finally:
        await session.close()


@router.get("/{session_id}/stream", summary="SSE de la sesión de aprendizaje")
async def stream_session(
    session_id: str,
    request: Request,
    since_seq: int = Query(default=0, ge=0),
    sessions=Depends(get_knowledge_session_service),
):
    ctx = require_permission(request, "sources:read")
    try:
        sid = UUID(session_id)
    except ValueError:
        raise HTTPException(400, "session_id must be a valid UUID")
    detail = await sessions.get_session_detail(ctx.organization_id, sid)
    if detail is None:
        raise HTTPException(404, "Learning session not found")

    return StreamingResponse(
        learning_session_event_source(
            ctx.organization_id,
            sid,
            since_seq=since_seq,
            repository=sessions.repository,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]

# =============================================================================
# Company Intelligence Studio API (§1-§25)
# =============================================================================
# Vistas compuestas y exploración en lenguaje natural. Tenant scoped, todo
# paginado y acotado. Consume el PUERTO del grafo (CompanyGraphService): la
# migración a Neo4j no debe tocar esta capa.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.core.domain.company_graph import EntityStatus
from src.platform.rbac.policy import require_permission

router = APIRouter(
    prefix="/api/v1/company-intelligence", tags=["CompanyIntelligence"]
)


def _studio():
    from src.company.wiring import company_studio_service

    return company_studio_service()


def _ask():
    from src.company.wiring import company_ask_service

    return company_ask_service()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_date", "message": "Invalid datetime"},
        ) from exc


def _statuses(values: list[str] | None) -> tuple[EntityStatus, ...]:
    if not values:
        return ()
    try:
        return tuple(EntityStatus(value) for value in values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_status", "message": "Invalid status"},
        ) from exc


def _not_found(message: str = "Entity not found") -> HTTPException:
    return HTTPException(status_code=404, detail={"error_code": "not_found", "message": message})


class AskIn(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(min_length=2, max_length=2000)
    agent_id: UUID | None = None
    workflow_id: UUID | None = None
    entity_id: UUID | None = Field(
        default=None,
        description="Contexto de página: permite preguntar '¿y sobre esta tabla?'",
    )
    as_of: str | None = None
    allow_knowledge: bool = True


# ---------------------------------------------------------------------------
# §2 Overview
# ---------------------------------------------------------------------------


@router.get("/overview", summary="Qué sabe Zent de esta empresa")
async def overview(request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().overview(ctx.organization_id)


# ---------------------------------------------------------------------------
# §3/§4 Company Map y exploración
# ---------------------------------------------------------------------------


@router.get("/map/{entity_id}", summary="Vecindad acotada de una entidad")
async def map_layer(
    entity_id: UUID,
    request: Request,
    direction: str = Query(default="both", pattern="^(both|in|out)$"),
    relationship_type: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0, le=1),
    as_of: str | None = None,
    max_nodes: int = Query(default=25, ge=1, le=200),
    max_edges: int = Query(default=60, ge=1, le=400),
    max_depth: int = Query(default=1, ge=1, le=3),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().map_layer(
            ctx.organization_id,
            entity_id,
            direction=direction,
            relationship_types=tuple(relationship_type or ()),
            statuses=_statuses(status),
            min_confidence=min_confidence,
            as_of=_parse_dt(as_of),
            max_nodes=max_nodes,
            max_edges=max_edges,
            max_depth=max_depth,
        )
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/entities", summary="Entidades del grafo con filtros (§23)")
async def list_entities(
    request: Request,
    entity_type: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200),
    domain: str | None = Query(default=None, max_length=120),
    status: list[str] | None = Query(default=None),
    current_only: bool = True,
    as_of: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    from src.company.studio import entity_view
    from src.company.wiring import company_graph_service

    rows = await company_graph_service().find_entities(
        ctx.organization_id,
        entity_type=entity_type,
        query=q,
        statuses=_statuses(status),
        current_only=current_only,
        as_of=_parse_dt(as_of),
        limit=limit,
        offset=offset,
    )
    items = [
        entity_view(entity)
        for entity in rows
        if domain is None or entity.domain == domain
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/domains", summary="Dominios con entidades registradas")
async def list_domains(request: Request):
    ctx = require_permission(request, "knowledge:read")
    from collections import defaultdict

    from src.company.wiring import company_graph_service

    rows = await company_graph_service().find_entities(
        ctx.organization_id, current_only=False, limit=200
    )
    counts: dict[str, int] = defaultdict(int)
    for entity in rows:
        counts[entity.domain] += 1
    return {
        "items": [
            {"domain": domain, "entities": count}
            for domain, count in sorted(counts.items())
        ]
    }


# ---------------------------------------------------------------------------
# §5/§6/§7 Detalle
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}", summary="Detalle de entidad (§5)")
async def entity_detail(
    entity_id: UUID,
    request: Request,
    as_of: str | None = None,
    max_edges: int = Query(default=60, ge=1, le=200),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().entity_detail(
            ctx.organization_id,
            entity_id,
            max_edges=max_edges,
            as_of=_parse_dt(as_of),
        )
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/concepts/{entity_id}", summary="Página de concepto de negocio (§6)")
async def concept_page(entity_id: UUID, request: Request, as_of: str | None = None):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().concept_page(
            ctx.organization_id, entity_id, as_of=_parse_dt(as_of)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "not_a_concept", "message": str(exc)},
        ) from exc


@router.get("/processes/{entity_id}", summary="Process Intelligence (§7/§8)")
async def process_page(
    entity_id: UUID,
    request: Request,
    max_runs: int = Query(default=200, ge=1, le=1000),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().process_page(
            ctx.organization_id, entity_id, max_runs=max_runs
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "not_a_process", "message": str(exc)},
        ) from exc


# ---------------------------------------------------------------------------
# §9/§10/§11 Impacto
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/impact", summary="¿Qué se afecta si X cambia?")
async def impact(
    entity_id: UUID,
    request: Request,
    direction: str = Query(default="both", pattern="^(both|in|out)$"),
    max_depth: int = Query(default=3, ge=1, le=4),
    max_nodes: int = Query(default=200, ge=1, le=500),
    as_of: str | None = None,
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().impact(
            ctx.organization_id,
            entity_id,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            as_of=_parse_dt(as_of),
        )
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


# ---------------------------------------------------------------------------
# §13/§14/§15/§16/§17/§18/§19
# ---------------------------------------------------------------------------


@router.get("/source-of-truth", summary="Fuente autoritativa por concepto")
async def source_of_truth(request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().source_of_truth(ctx.organization_id)


@router.get("/knowledge-gaps", summary="Conocimiento incompleto")
async def knowledge_gaps(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().knowledge_gaps(ctx.organization_id, limit=limit, offset=offset)


@router.get("/changes", summary="Timeline de cambios (§15)")
async def changes(
    request: Request,
    since: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().changes(
        ctx.organization_id, since=_parse_dt(since), limit=limit, offset=offset
    )


@router.get("/entities/{entity_id}/changes", summary="¿Qué cambió en esta entidad?")
async def entity_changes(entity_id: UUID, request: Request, as_of: str | None = None):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().entity_changes(
            ctx.organization_id, entity_id, as_of=_parse_dt(as_of)
        )
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/entities/{entity_id}/memory", summary="Qué aprendió Zent (§20)")
async def entity_memory(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().entity_memory(ctx.organization_id, entity_id, limit=limit)
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get(
    "/entities/{entity_id}/conversations",
    summary="Conversaciones donde la entidad fue relevante (§21)",
)
async def entity_conversations(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _studio().entity_conversations(
            ctx.organization_id, entity_id, limit=limit
        )
    except ValueError as exc:
        raise _not_found(str(exc)) from exc


@router.get("/institutional", summary="Personas, roles, equipos y responsables (§17)")
async def institutional(request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().institutional(ctx.organization_id)


@router.get("/risks", summary="Candidatos a punto único de falla (§18)")
async def risks(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    ctx = require_permission(request, "knowledge:read")
    return {"items": await _studio().risks(ctx.organization_id, limit=limit)}


@router.get("/health", summary="Salud del conocimiento del grafo (§19)")
async def health(request: Request):
    ctx = require_permission(request, "knowledge:read")
    return await _studio().knowledge_health(ctx.organization_id)


# ---------------------------------------------------------------------------
# §12 Ask your Company
# ---------------------------------------------------------------------------


@router.post("/ask", summary="Preguntar en lenguaje natural sobre la empresa")
async def ask(body: AskIn, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        answer = await _ask().ask(
            ctx.organization_id,
            body.question,
            agent_id=body.agent_id,
            workflow_id=body.workflow_id,
            entity_id=body.entity_id,
            as_of=_parse_dt(body.as_of),
            allow_knowledge=body.allow_knowledge,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_question", "message": str(exc)[:240]},
        ) from exc
    return answer.to_dict()


@router.get("/ask/examples", summary="Preguntas de ejemplo")
async def ask_examples(request: Request):
    require_permission(request, "knowledge:read")
    return {
        "items": [
            "¿Qué procesos dependen de este sistema?",
            "¿Qué usa esta tabla?",
            "¿Qué agentes dependen de esta API?",
            "¿Cuál es la fuente de verdad de ticket status?",
            "¿Qué cambió en este proceso?",
            "¿Qué conocimiento falta?",
            "¿Qué se vería afectado si este sistema no está disponible?",
            "¿Qué aprendió Zent sobre esta tabla?",
        ]
    }

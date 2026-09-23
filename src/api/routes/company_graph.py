# =============================================================================
# Company Intelligence API — tenant scoped, paginado.
# entities / relationships / neighbors / paths / impact / history /
# source authority / concept mappings. Lectura: knowledge:read.
# Mutaciones y confirmaciones: knowledge:write. Authority: admin.
# =============================================================================
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.core.domain.company_graph import EntityStatus, ProvenanceRef
from src.core.ports.company_graph import (
    GraphTraversalLimits,
    RelationshipFilter,
)
from src.platform.rbac.policy import require_organization_admin, require_permission

router = APIRouter(prefix="/api/v1/company-graph", tags=["CompanyGraph"])


def _service():
    from src.company.wiring import company_graph_service

    return company_graph_service()


def _authority():
    from src.company.wiring import company_authority_service

    return company_authority_service()


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
        return tuple(EntityStatus(v) for v in values)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_status", "message": "Invalid status"},
        ) from exc


def _entity_to_dict(entity) -> dict:
    return {
        "id": str(entity.id),
        "entity_type": entity.entity_type,
        "canonical_name": entity.canonical_name,
        "display_name": entity.display_name,
        "description": entity.description,
        "domain": entity.domain,
        "aliases": list(entity.aliases),
        "status": entity.status.value,
        "confidence": entity.confidence,
        "authority_level": (
            entity.authority_level.value if entity.authority_level else None
        ),
        "source": entity.source,
        "source_ref": entity.source_ref,
        "evidence": [p.to_dict() for p in entity.evidence],
        "metadata": entity.metadata,
        "valid_from": entity.valid_from.isoformat() if entity.valid_from else None,
        "valid_to": entity.valid_to.isoformat() if entity.valid_to else None,
    }


def _rel_to_dict(rel) -> dict:
    return {
        "id": str(rel.id),
        "from_entity_id": str(rel.from_entity_id),
        "to_entity_id": str(rel.to_entity_id),
        "relationship_type": rel.relationship_type,
        "status": rel.status.value,
        "confidence": rel.confidence,
        "source": rel.source,
        "source_ref": rel.source_ref,
        "evidence_refs": [p.to_dict() for p in rel.evidence_refs],
        "metadata": rel.metadata,
        "valid_from": rel.valid_from.isoformat() if rel.valid_from else None,
        "valid_to": rel.valid_to.isoformat() if rel.valid_to else None,
    }


def _limits(
    max_depth: int = 4, max_nodes: int = 200, max_edges: int = 500
) -> GraphTraversalLimits:
    try:
        return GraphTraversalLimits(
            max_depth=max_depth, max_nodes=max_nodes, max_edges=max_edges
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_limits", "message": str(exc)},
        ) from exc


def _rel_filter(
    relationship_types: list[str] | None,
    statuses: list[str] | None,
    current_only: bool,
    min_confidence: float | None,
    as_of: str | None,
) -> RelationshipFilter:
    return RelationshipFilter(
        relationship_types=tuple(relationship_types or ()),
        statuses=_statuses(statuses),
        current_only=current_only,
        min_confidence=min_confidence,
        as_of=_parse_dt(as_of),
    )


class UpsertEntityIn(BaseModel):
    model_config = {"extra": "forbid"}

    entity_type: str = Field(max_length=64)
    canonical_name: str = Field(max_length=320)
    display_name: str = Field(default="", max_length=320)
    description: str = Field(default="", max_length=4000)
    domain: str = Field(default="general", max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    status: EntityStatus = EntityStatus.DISCOVERED
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: str = Field(default="", max_length=200)
    source_ref: str = Field(default="", max_length=512)
    evidence: list[dict] = Field(default_factory=list, max_length=50)
    metadata: dict = Field(default_factory=dict)
    valid_from: str | None = None
    valid_to: str | None = None


class ProposeRelationshipIn(BaseModel):
    model_config = {"extra": "forbid"}

    from_entity_id: UUID
    to_entity_id: UUID
    relationship_type: str = Field(max_length=64)
    source: str = Field(default="", max_length=200)
    source_ref: str = Field(default="", max_length=512)
    evidence: list[dict] = Field(default_factory=list, max_length=50)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_from: str | None = None
    valid_to: str | None = None
    metadata: dict = Field(default_factory=dict)
    auto_confirm_structural: bool = False


class ConfirmRelationshipIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: EntityStatus


class AuthorityRuleIn(BaseModel):
    model_config = {"extra": "forbid"}

    domain: str = Field(default="general", max_length=120)
    concept: str = Field(default="", max_length=160)
    source_name: str = Field(max_length=200)
    source_type: str = Field(default="connector", max_length=20)
    authority_level: str = Field(default="informational", max_length=16)
    priority: int = Field(default=1, ge=1, le=1000)
    effective_from: str | None = None
    effective_to: str | None = None


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@router.get("/entities", summary="Buscar entidades del tenant")
async def list_entities(
    request: Request,
    entity_type: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    status: list[str] | None = Query(default=None),
    current_only: bool = True,
    as_of: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    rows = await _service().find_entities(
        ctx.organization_id,
        entity_type=entity_type,
        query=q,
        statuses=_statuses(status),
        current_only=current_only,
        as_of=_parse_dt(as_of),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_entity_to_dict(e) for e in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/entities/{entity_id}", summary="Ver una entidad")
async def get_entity(entity_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    entity = await _service().get_entity(ctx.organization_id, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail={"error_code": "not_found"})
    return _entity_to_dict(entity)


@router.post("/entities", status_code=201, summary="Crear o actualizar entidad")
async def upsert_entity(body: UpsertEntityIn, request: Request):
    from src.core.domain.company_graph import CompanyEntity

    ctx = require_permission(request, "knowledge:write")
    try:
        evidence = tuple(ProvenanceRef.from_dict(p) for p in body.evidence)
        entity = CompanyEntity(
            organization_id=ctx.organization_id,
            entity_type=body.entity_type,
            canonical_name=body.canonical_name,
            display_name=body.display_name,
            description=body.description,
            domain=body.domain,
            aliases=tuple(body.aliases),
            status=body.status,
            confidence=body.confidence,
            source=body.source,
            source_ref=body.source_ref,
            evidence=evidence,
            metadata=body.metadata,
            valid_from=_parse_dt(body.valid_from),
            valid_to=_parse_dt(body.valid_to),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_entity", "message": str(exc)[:240]},
        ) from exc
    saved = await _service().upsert_entity(entity)
    return _entity_to_dict(saved)


@router.get("/entities/{entity_id}/explain", summary="¿Por qué Zent cree esto?")
async def explain_entity(entity_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:read")
    try:
        return await _service().explain(ctx.organization_id, entity_id)
    except ValueError:
        raise HTTPException(status_code=404, detail={"error_code": "not_found"})


@router.get("/entities/{entity_id}/history", summary="Historial de la entidad")
async def entity_history(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    rows = await _service().history(
        ctx.organization_id, entity_id, limit=limit, offset=offset
    )
    return {
        "items": [_rel_to_dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/entities/{entity_id}/mappings",
    summary="Mappings técnicos de un concepto",
)
async def concept_mappings(entity_id: UUID, request: Request, as_of: str | None = None):
    ctx = require_permission(request, "knowledge:read")
    rows = await _service().concept_mappings(
        ctx.organization_id, entity_id, as_of=_parse_dt(as_of)
    )
    return {"items": [_rel_to_dict(r) for r in rows]}


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------


@router.get("/relationships", summary="Buscar relaciones del tenant")
async def list_relationships(
    request: Request,
    from_entity_id: UUID | None = None,
    to_entity_id: UUID | None = None,
    relationship_type: list[str] | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    current_only: bool = True,
    as_of: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    ctx = require_permission(request, "knowledge:read")
    rows = await _service().find_relationships(
        ctx.organization_id,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relationship_types=tuple(relationship_type or ()),
        statuses=_statuses(status),
        current_only=current_only,
        as_of=_parse_dt(as_of),
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_rel_to_dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/relationships", status_code=201, summary="Proponer una relación"
)
async def propose_relationship(body: ProposeRelationshipIn, request: Request):
    ctx = require_permission(request, "knowledge:write")
    try:
        evidence = tuple(ProvenanceRef.from_dict(p) for p in body.evidence)
        rel = await _service().propose_relationship(
            ctx.organization_id,
            body.from_entity_id,
            body.to_entity_id,
            body.relationship_type,
            source=body.source,
            source_ref=body.source_ref,
            evidence=evidence,
            confidence=body.confidence,
            valid_from=_parse_dt(body.valid_from),
            valid_to=_parse_dt(body.valid_to),
            metadata=body.metadata,
            auto_confirm_structural=body.auto_confirm_structural,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_relationship", "message": str(exc)[:240]},
        ) from exc
    return _rel_to_dict(rel)


@router.post(
    "/relationships/{relationship_id}/confirm",
    summary="Confirmar o transicionar una relación",
)
async def confirm_relationship(
    relationship_id: UUID, body: ConfirmRelationshipIn, request: Request
):
    ctx = require_permission(request, "knowledge:write")
    try:
        rel = await _service().confirm_relationship(
            ctx.organization_id, relationship_id, status=body.status
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_transition", "message": str(exc)[:240]},
        ) from exc
    return _rel_to_dict(rel)


@router.post(
    "/relationships/{relationship_id}/deprecate",
    summary="Deprecar una relación",
)
async def deprecate_relationship(relationship_id: UUID, request: Request):
    ctx = require_permission(request, "knowledge:write")
    try:
        rel = await _service().deprecate_relationship(
            ctx.organization_id, relationship_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_transition", "message": str(exc)[:240]},
        ) from exc
    return _rel_to_dict(rel)


# ---------------------------------------------------------------------------
# Graph queries
# ---------------------------------------------------------------------------


@router.get("/entities/{entity_id}/neighbors", summary="Vecinos a un salto")
async def neighbors(
    entity_id: UUID,
    request: Request,
    direction: str = "both",
    relationship_type: list[str] | None = Query(default=None),
    current_only: bool = True,
    max_edges: int = Query(default=100, ge=1, le=1000),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        hood = await _service().neighbors(
            ctx.organization_id,
            entity_id,
            direction=direction,
            relationship_filter=_rel_filter(
                relationship_type, None, current_only, None, None
            ),
            limits=_limits(max_nodes=500, max_edges=max_edges),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_query", "message": str(exc)[:240]},
        ) from exc
    return {
        "entities": [_entity_to_dict(e) for e in hood.entities],
        "relationships": [_rel_to_dict(r) for r in hood.relationships],
        "truncated": hood.truncated,
    }


@router.get("/paths", summary="Camino entre dos entidades")
async def find_path(
    request: Request,
    from_entity_id: UUID = Query(),
    to_entity_id: UUID = Query(),
    max_depth: int = Query(default=4, ge=1, le=10),
):
    ctx = require_permission(request, "knowledge:read")
    path = await _service().find_path(
        ctx.organization_id,
        from_entity_id,
        to_entity_id,
        limits=_limits(max_depth=max_depth),
    )
    if path is None:
        raise HTTPException(status_code=404, detail={"error_code": "no_path"})
    return {
        "entities": [_entity_to_dict(e) for e in path.entities],
        "relationships": [_rel_to_dict(r) for r in path.relationships],
    }


@router.get("/entities/{entity_id}/impact", summary="Análisis de impacto")
async def impact(
    entity_id: UUID,
    request: Request,
    direction: str = "both",
    max_depth: int = Query(default=4, ge=1, le=10),
    max_nodes: int = Query(default=200, ge=1, le=2000),
):
    ctx = require_permission(request, "knowledge:read")
    try:
        result = await _service().impact_analysis(
            ctx.organization_id,
            entity_id,
            direction=direction,
            limits=_limits(max_depth=max_depth, max_nodes=max_nodes),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_query", "message": str(exc)[:240]},
        ) from exc
    return {
        "root": _entity_to_dict(result.root) if result.root else None,
        "entities": [_entity_to_dict(e) for e in result.entities],
        "relationships": [_rel_to_dict(r) for r in result.relationships],
        "by_type": result.by_type,
        "truncated": result.truncated,
    }


# ---------------------------------------------------------------------------
# Source authority (configurable por tenant)
# ---------------------------------------------------------------------------


@router.get("/authority", summary="Reglas de authority del tenant")
async def list_authority(
    request: Request, domain: str | None = Query(default=None, max_length=120)
):
    ctx = require_permission(request, "knowledge:read")
    rules = await _authority().list_rules(ctx.organization_id, domain=domain)
    return {
        "items": [
            {
                "domain": r.domain,
                "concept": r.concept,
                "source_name": r.source_name,
                "source_type": r.source_type,
                "authority_level": r.authority_level.value,
                "priority": r.priority,
            }
            for r in rules
        ]
    }


@router.post("/authority", status_code=201, summary="Configurar regla de authority")
async def upsert_authority(body: AuthorityRuleIn, request: Request):
    from src.company.service import AuthorityRule
    from src.core.domain.company_graph import SourceAuthorityLevel

    ctx = require_organization_admin(request)
    try:
        level = SourceAuthorityLevel(body.authority_level.strip().lower())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_level", "message": "Invalid authority level"},
        ) from exc
    rule = AuthorityRule(
        organization_id=ctx.organization_id,
        domain=body.domain,
        concept=body.concept,
        source_name=body.source_name,
        source_type=body.source_type,
        authority_level=level,
        priority=body.priority,
        effective_from=_parse_dt(body.effective_from),
        effective_to=_parse_dt(body.effective_to),
    )
    saved = await _authority().upsert_rule(rule)
    return {
        "domain": saved.domain,
        "concept": saved.concept,
        "source_name": saved.source_name,
        "authority_level": saved.authority_level.value,
        "priority": saved.priority,
    }

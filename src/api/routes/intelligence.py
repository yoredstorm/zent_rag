# =============================================================================
# Intelligence Routes — traces de answerability + definiciones empresariales
# =============================================================================
# GET /api/v1/intelligence/traces/{trace_id}   — traza org-scoped (rag:read)
# GET/POST/PUT/DELETE /api/v1/intelligence/definitions — definiciones aprobadas
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.deps import (
    get_business_definition_registry,
    get_intelligence_store,
    get_verified_query_service,
)
from src.core.domain.verified_query import VerifiedQueryStatus
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.definitions import BusinessDefinitionRegistry
from src.intelligence.store import PostgresIntelligenceStore
from src.intelligence.verified_queries import VerifiedQueryService
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/intelligence", tags=["Intelligence"])

_VALID_STATUSES = {"draft", "approved", "deprecated"}
_VALID_DATA_TYPES = {"metric", "dimension", "concept", "status_value"}


class BusinessDefinitionCreate(BaseModel):
    """Payload de creación/actualización de una definición empresarial."""

    concept: str = Field(min_length=1, max_length=160)
    definition: str = Field(min_length=1, max_length=8000)
    expression: str | None = Field(default=None, max_length=4000)
    data_type: str = Field(default="concept", max_length=20)
    status: str = Field(default="approved", max_length=20)
    authoritative_source_id: str | None = Field(default=None, max_length=120)
    synonyms: list[str] = Field(default_factory=list)
    owner: str | None = Field(default=None, max_length=120)

    @field_validator("concept")
    @classmethod
    def _normalize_concept(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("concept no puede estar vacío")
        return normalized

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value: str) -> str:
        if value not in _VALID_STATUSES:
            raise ValueError(f"status debe ser uno de {sorted(_VALID_STATUSES)}")
        return value

    @field_validator("data_type")
    @classmethod
    def _validate_data_type(cls, value: str) -> str:
        if value not in _VALID_DATA_TYPES:
            raise ValueError(
                f"data_type debe ser uno de {sorted(_VALID_DATA_TYPES)}"
            )
        return value


def _tenant_ctx(request: Request):
    return getattr(request.state, "tenant_context", None)


def _definition_payload(definition) -> dict:
    return {
        "id": str(definition.id),
        "concept": definition.concept,
        "definition": definition.definition,
        "expression": definition.expression,
        "data_type": definition.data_type,
        "status": definition.status,
        "authoritative_source_id": definition.authoritative_source_id,
        "synonyms": definition.synonyms,
        "owner": definition.owner,
        "version": definition.version,
        "effective_from": (
            definition.effective_from.isoformat()
            if definition.effective_from
            else None
        ),
        "effective_to": (
            definition.effective_to.isoformat() if definition.effective_to else None
        ),
        "approved_by": str(definition.approved_by) if definition.approved_by else None,
        "provenance": definition.provenance,
        "created_by": str(definition.created_by) if definition.created_by else None,
        "created_at": definition.created_at.isoformat(),
        "updated_at": definition.updated_at.isoformat(),
    }


@router.get(
    "/traces/{trace_id}",
    summary="Traza de una consulta del Intelligence Layer",
    responses={
        200: {"description": "Traza completa org-scoped"},
        401: {"description": "Autenticación requerida"},
        404: {"description": "Traza no encontrada (o de otra organización)"},
    },
)
async def get_trace(
    trace_id: str,
    request: Request,
    store: PostgresIntelligenceStore = Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "rag:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    trace = await store.get_trace(ctx.organization_id, trace_id)
    if trace is None:
        raise HTTPException(404, "Trace not found")
    return trace


@router.get(
    "/why/{query_id}",
    summary="Why does Zent know this? (inspección de una respuesta)",
    responses={
        200: {"description": "Explicación de la respuesta (conceptos, versiones, fuentes, evidencia)"},
        404: {"description": "Traza no encontrada (o de otra organización)"},
    },
)
async def why_knows(
    query_id: UUID,
    request: Request,
    store: PostgresIntelligenceStore = Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "rag:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    trace = await store.get_trace_by_query_id(ctx.organization_id, query_id)
    if trace is None:
        raise HTTPException(404, "Trace not found")
    understanding = trace.get("understanding") or {}
    decision = trace.get("decision") or {}

    # Versión de conceptos desde el glosario (para la explicación).
    concept_versions: dict[str, dict] = {}
    for concept in understanding.get("concepts") or []:
        try:
            definition = await store.get_definition(ctx.organization_id, concept)
            if definition:
                concept_versions[concept] = {
                    "version": definition.version,
                    "status": definition.status,
                    "provenance": definition.provenance,
                    "effective_from": (
                        definition.effective_from.isoformat()
                        if definition.effective_from
                        else None
                    ),
                }
        except Exception:  # noqa: BLE001
            pass

    return {
        "query_id": str(query_id),
        "question": trace.get("user_query"),
        "answer": trace.get("answer"),
        "status": trace.get("status"),
        "intent": understanding.get("intent"),
        "business_concepts": understanding.get("concepts") or [],
        "concept_versions": concept_versions,
        "source_of_truth": await _authority_for_concepts(
            ctx.organization_id, understanding.get("concepts") or []
        ),
        "physical_sources": [
            {
                "type": e.get("type"),
                "source_name": e.get("source_name"),
                "authority_level": e.get("authority_level"),
                "freshness": e.get("freshness"),
            }
            for e in (trace.get("evidence") or [])
        ],
        "model": trace.get("model"),
        "method": trace.get("method"),
        "trace_id": trace.get("trace_id"),
        "confidence_explanation": decision.get("confidence_level"),
        "reason_codes": decision.get("reason_codes") or [],
        "created_at": trace.get("created_at"),
    }


@router.get(
    "/why-not/{query_id}",
    summary="Why couldn't Zent answer? (abstención explicada)",
    responses={
        200: {"description": "Qué faltó, qué había disponible, impacto y recomendación"},
        404: {"description": "Traza no encontrada (o de otra organización)"},
    },
)
async def why_not(
    query_id: UUID,
    request: Request,
    store: PostgresIntelligenceStore = Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "rag:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    trace = await store.get_trace_by_query_id(ctx.organization_id, query_id)
    if trace is None:
        raise HTTPException(404, "Trace not found")
    decision = trace.get("decision") or {}
    question = trace.get("user_query") or ""
    status = trace.get("status") or decision.get("status") or "UNKNOWN"

    advisor_payload: dict = {"available": [], "missing": [], "recommendation": None}
    try:
        from src.api.deps import get_context_advisor

        gap = {
            "gap_type": status,
            "concept": (decision.get("missing_context") or [""])[0]
            .replace("Definition of ", ""),
            "impact": {},
        }
        advised = await get_context_advisor().advise(ctx.organization_id, question, gap=gap)
        advisor_payload = {
            "available": advised.get("available") or decision.get("found") or [],
            "missing": advised.get("missing") or decision.get("missing_context") or [],
            "recommendation": advised.get("recommendation"),
        }
    except Exception:  # noqa: BLE001
        advisor_payload = {
            "available": decision.get("found") or [],
            "missing": (
                decision.get("missing_context") or decision.get("missing_data") or []
            ),
            "recommendation": None,
        }

    return {
        "query_id": str(query_id),
        "question": question,
        "status": status,
        "answerable": bool(decision.get("answerable")),
        "confidence": decision.get("confidence_level"),
        "reason_codes": decision.get("reason_codes") or [],
        "available": advisor_payload["available"],
        "missing": advisor_payload["missing"],
        "recommendation": advisor_payload["recommendation"],
        "impact": {
            "query_count_30d": 0,
            "users": 0,
            "agents": 0,
        },
        "trace_id": trace.get("trace_id"),
    }


async def _authority_for_concepts(
    organization_id: UUID, concepts: list[str]
) -> list[dict]:
    """Fuentes autoritativas de la org (fail-soft)."""
    try:
        from src.api.deps import get_catalog_store
        from src.catalog.authority import AuthorityService

        return await AuthorityService(get_catalog_store()).list(organization_id)
    except Exception:  # noqa: BLE001
        return []


@router.get(
    "/definitions",
    summary="Definiciones empresariales aprobadas de la organización",
)
async def list_definitions(
    request: Request,
    registry: BusinessDefinitionRegistry = Depends(get_business_definition_registry),
) -> list[dict]:
    require_permission(request, "org:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    definitions = await registry.get_all(ctx.organization_id)
    return [_definition_payload(d) for d in definitions]


@router.post(
    "/definitions",
    status_code=201,
    summary="Crea o actualiza una definición empresarial aprobada",
)
async def upsert_definition(
    body: BusinessDefinitionCreate,
    request: Request,
    registry: BusinessDefinitionRegistry = Depends(get_business_definition_registry),
) -> dict:
    require_permission(request, "org:write")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    from uuid import uuid4

    from src.core.domain.intelligence import BusinessDefinition

    definition = BusinessDefinition(
        id=uuid4(),
        organization_id=ctx.organization_id,
        concept=body.concept,
        definition=body.definition,
        expression=body.expression,
        data_type=body.data_type,
        status=body.status,
        authoritative_source_id=body.authoritative_source_id,
        synonyms=body.synonyms,
        owner=body.owner,
        created_by=ctx.user_id,
        approved_by=ctx.user_id if body.status == "approved" else None,
        provenance="APPROVED" if body.status == "approved" else "OBSERVED",
    )
    saved = await registry.upsert(definition)
    return _definition_payload(saved)


@router.delete(
    "/definitions/{concept}",
    summary="Elimina una definición empresarial",
    responses={404: {"description": "Definición no encontrada"}},
)
async def delete_definition(
    concept: str,
    request: Request,
    registry: BusinessDefinitionRegistry = Depends(get_business_definition_registry),
) -> dict:
    require_permission(request, "org:write")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    deleted = await registry.delete(ctx.organization_id, concept.strip().lower())
    if not deleted:
        raise HTTPException(404, "Definition not found")
    return {"deleted": concept.strip().lower()}


# ---------------------------------------------------------------------------
# Verified Queries (Phase 26C)
# ---------------------------------------------------------------------------


class VerifiedQueryBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    canonical_question: str = Field(min_length=1, max_length=4000)
    verified_sql: str = Field(min_length=1, max_length=50000)
    description: str = ""
    question_variants: list[str] = Field(default_factory=list)
    semantic_ast: dict = Field(default_factory=dict)
    dialect: str = "postgres"
    status: str = "DRAFT"
    metric_dependencies: list[str] = Field(default_factory=list)
    concept_dependencies: list[str] = Field(default_factory=list)
    table_dependencies: list[str] = Field(default_factory=list)


class MappingReviewBody(BaseModel):
    action: str = Field(description="APPROVE | REJECT | EDIT_AND_APPROVE")
    physical_predicate: str | None = None


@router.get("/verified-queries", summary="Lista verified queries del tenant")
async def list_verified_queries(
    request: Request,
    status: str | None = None,
    service: VerifiedQueryService = Depends(get_verified_query_service),
) -> dict:
    require_permission(request, "catalog:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    await service.store.ensure_tables()
    items = await service.store.list(ctx.organization_id, status=status)
    return {"items": [i.to_dict() for i in items]}


@router.post(
    "/verified-queries",
    status_code=201,
    summary="Crea o actualiza una verified query",
)
async def create_verified_query(
    body: VerifiedQueryBody,
    request: Request,
    service: VerifiedQueryService = Depends(get_verified_query_service),
) -> dict:
    require_permission(request, "catalog:write")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    try:
        status = VerifiedQueryStatus(body.status.upper())
    except ValueError as exc:
        raise HTTPException(400, f"Invalid status: {body.status}") from exc
    await service.store.ensure_tables()
    # Verified SQL must still be treated as untrusted until validation elsewhere
    item = await service.create(
        ctx.organization_id,
        name=body.name,
        canonical_question=body.canonical_question,
        verified_sql=body.verified_sql,
        semantic_ast=body.semantic_ast,
        question_variants=body.question_variants,
        dialect=body.dialect,
        status=status,
        metric_dependencies=body.metric_dependencies,
        concept_dependencies=body.concept_dependencies,
        table_dependencies=body.table_dependencies,
        approved_by=ctx.user_id if status == VerifiedQueryStatus.VERIFIED else None,
    )
    return item.to_dict()


@router.get(
    "/verified-queries/search",
    summary="Busca verified queries por pregunta + semántica",
)
async def search_verified_queries(
    request: Request,
    q: str,
    service: VerifiedQueryService = Depends(get_verified_query_service),
) -> dict:
    require_permission(request, "catalog:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    await service.store.ensure_tables()
    hits = await service.search(ctx.organization_id, question=q)
    return {"matches": [h.to_dict() for h in hits]}


@router.get(
    "/mapping-suggestions",
    summary="Sugerencias INFERRED de mapeo físico (requieren aprobación)",
)
async def list_mapping_suggestions(
    request: Request,
    status: str | None = "INFERRED",
    service: VerifiedQueryService = Depends(get_verified_query_service),
) -> dict:
    require_permission(request, "catalog:read")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    await service.store.ensure_tables()
    items = await service.store.list_mapping_suggestions(
        ctx.organization_id, status=status
    )
    return {"items": [i.to_dict() for i in items]}


@router.post(
    "/mapping-suggestions/{suggestion_id}/review",
    summary="APPROVE / REJECT / EDIT_AND_APPROVE — nunca auto-promoción",
)
async def review_mapping_suggestion(
    suggestion_id: UUID,
    body: MappingReviewBody,
    request: Request,
    service: VerifiedQueryService = Depends(get_verified_query_service),
) -> dict:
    require_permission(request, "catalog:write")
    ctx = _tenant_ctx(request)
    if ctx is None or not ctx.organization_id:
        raise HTTPException(401, "Tenant context required")
    await service.store.ensure_tables()
    try:
        updated = await service.store.review_mapping_suggestion(
            ctx.organization_id,
            suggestion_id,
            action=body.action,
            reviewed_by=ctx.user_id,
            physical_predicate=body.physical_predicate,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if updated is None:
        raise HTTPException(404, "Suggestion not found")
    return updated.to_dict()

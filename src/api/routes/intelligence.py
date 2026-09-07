# =============================================================================
# Intelligence Routes — traces de answerability + definiciones empresariales
# =============================================================================
# GET /api/v1/intelligence/traces/{trace_id}   — traza org-scoped (rag:read)
# GET/POST/PUT/DELETE /api/v1/intelligence/definitions — definiciones aprobadas
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.api.deps import get_business_definition_registry, get_intelligence_store
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.definitions import BusinessDefinitionRegistry
from src.intelligence.store import PostgresIntelligenceStore
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
        created_by=ctx.user_id,
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

# =============================================================================
# Intelligence Routes ÔÇö traces de answerability + definiciones empresariales
# =============================================================================
# GET /api/v1/intelligence/traces/{trace_id}   ÔÇö traza org-scoped (rag:read)
# GET/POST/PUT/DELETE /api/v1/intelligence/definitions ÔÇö definiciones aprobadas
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
    """Payload de creaci├│n/actualizaci├│n de una definici├│n empresarial."""

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
            raise ValueError("concept no puede estar vac├¡o")
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
        401: {"description": "Autenticaci├│n requerida"},
        404: {"description": "Traza no encontrada (o de otra organizaci├│n)"},
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
    summary="Why does Zent know this? (inspecci├│n de una respuesta)",
    responses={
        200: {"description": "Explicaci├│n de la respuesta (conceptos, versiones, fuentes, evidencia)"},
        404: {"description": "Traza no encontrada (o de otra organizaci├│n)"},
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

    # Versi├│n de conceptos desde el glosario (para la explicaci├│n).
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
    summary="Why couldn't Zent answer? (abstenci├│n explicada)",
    responses={
        200: {"description": "Qu├® falt├│, qu├® hab├¡a disponible, impacto y recomendaci├│n"},
        404: {"description": "Traza no encontrada (o de otra organizaci├│n)"},
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
    summary="Definiciones empresariales aprobadas de la organizaci├│n",
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
    summary="Crea o actualiza una definici├│n empresarial aprobada",
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
    summary="Elimina una definici├│n empresarial",
    responses={404: {"description": "Definici├│n no encontrada"}},
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
    summary="Busca verified queries por pregunta + sem├íntica",
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
    summary="Sugerencias INFERRED de mapeo f├¡sico (requieren aprobaci├│n)",
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
    summary="APPROVE / REJECT / EDIT_AND_APPROVE ÔÇö nunca auto-promoci├│n",
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
# ---------------------------------------------------------------------------
# Phase 32C — Business Results (inbox), copilot y stats
# ---------------------------------------------------------------------------

async def _workspace_id(request) -> UUID | None:
    from src.platform.workspaces.context import (
        get_active_workspace_id,
        workspace_header_or_none,
    )

    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        return None
    header = workspace_header_or_none(request)
    if header is not None:
        return header
    try:
        active = await get_active_workspace_id(ctx.organization_id, ctx.user_id)
        if active is not None:
            return active
    except Exception:
        pass
    return None


class DraftIn(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)


@router.get("/results", summary="Inbox de resultados de inteligencia")
async def intelligence_results(
    request: Request,
    section: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    since_minutes: int | None = None,
):
    ctx = require_permission(request, "intelligence:read")
    from src.platform.intelligence.results import list_results

    return await list_results(
        ctx.organization_id,
        workspace_id=await _workspace_id(request),
        section=section,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
        since_minutes=since_minutes,
    )


@router.get("/results/{result_id}", summary="Detalle de resultado")
async def intelligence_result_detail(result_id: str, request: Request):
    ctx = require_permission(request, "intelligence:read")
    from src.platform.intelligence.results import get_result

    result = await get_result(ctx.organization_id, UUID(result_id))
    if result is None:
        raise HTTPException(404, "Resultado no encontrado")
    return result


@router.post("/workflow/draft", summary="Copiloto: lenguaje natural → draft")
async def intelligence_workflow_draft(body: DraftIn, request: Request):
    ctx = require_permission(request, "workflows:create")
    from src.platform.workflows.copilot import build_draft

    prompt = (body.prompt or "").strip()
    if len(prompt) < 8:
        raise HTTPException(400, "describe qué quieres automatizar")
    plan = build_draft(prompt)
    from src.platform.workflows.capabilities import draft_marketplace_flags

    marketplace = await draft_marketplace_flags(
        ctx.organization_id, plan.steps, workspace_id=await _workspace_id(request)
    )
    return {
        "name": plan.name,
        "trigger_type": plan.trigger_type,
        "trigger_config": plan.trigger_config,
        "steps": plan.steps,
        "questions": plan.questions,
        "source_hint": plan.source_hint,
        "integration_hint": plan.integration_hint,
        "marketplace": marketplace,
        "draft": True,
        "must_review": True,
    }


@router.get("/assist/options", summary="Opciones para smart pickers")
async def intelligence_assist_options(request: Request):
    ctx = require_permission(request, "intelligence:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session
    from src.platform.marketplace.runtime import list_installs

    session = await get_async_session()
    try:
        kbs = (
            await session.execute(
                text(
                    "SELECT id, name FROM knowledge_bases "
                    "WHERE organization_id = :oid ORDER BY name"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchall()
        agents = (
            await session.execute(
                text(
                    "SELECT id, name FROM agents WHERE organization_id = :oid "
                    "AND status IN ('configured','ready','deployed') ORDER BY name"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchall()
        try:
            sources = (
                await session.execute(
                    text(
                        "SELECT id, name, source_type FROM catalog_sources "
                        "WHERE organization_id = :oid ORDER BY name LIMIT 100"
                    ),
                    {"oid": ctx.organization_id},
                )
            ).fetchall()
        except Exception:
            sources = []
    finally:
        await session.close()

    installs = await list_installs(ctx.organization_id, await _workspace_id(request))
    return {
        "knowledge_bases": [{"id": str(k.id), "name": k.name} for k in kbs],
        "agents": [{"id": str(a.id), "name": a.name} for a in agents],
        "data_sources": [{"id": str(s.id), "name": s.name, "type": s.source_type} for s in sources],
        "integrations": [
            {
                "install_id": i["id"],
                "slug": i["integration"]["slug"],
                "name": i["integration"]["name"],
                "status": i["status"],
            }
            for i in installs["installs"]
        ],
    }


@router.get("/automations/stats", summary="Stats para Automations Home")
async def intelligence_automations_stats(request: Request):
    ctx = require_permission(request, "intelligence:read")
    from sqlalchemy import text

    from src.infrastructure.postgres.session import get_async_session

    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT COUNT(*) FROM workflows WHERE organization_id = :oid AND status = 'active') AS active, "
                    "(SELECT COUNT(*) FROM workflow_runs WHERE organization_id = :oid "
                    "AND status = 'failed' AND started_at > NOW() - interval '24 hours') AS failed_24h, "
                    "(SELECT COUNT(*) FROM workflow_runs WHERE organization_id = :oid "
                    "AND started_at > NOW() - interval '24 hours') AS runs_24h, "
                    "(SELECT COUNT(*) FROM workflow_runs r JOIN workflows w ON w.id = r.workflow_id "
                    "WHERE w.organization_id = :oid AND r.status = 'succeeded' "
                    "AND r.started_at > NOW() - interval '30 days') AS runs_30d "
                    "FROM (SELECT 1) x"
                ),
                {"oid": ctx.organization_id},
            )
        ).fetchone()
        spend = (
            await session.execute(
                text(
                    "SELECT COALESCE(SUM(customer_cost), 0) FROM integration_usage_ledger "
                    "WHERE organization_id = :oid AND created_at > NOW() - interval '24 hours'"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
        ext_calls_24h = (
            await session.execute(
                text(
                    "SELECT COUNT(*) FROM integration_usage_ledger WHERE organization_id = :oid "
                    "AND created_at > NOW() - interval '24 hours'"
                ),
                {"oid": ctx.organization_id},
            )
        ).scalar()
    finally:
        await session.close()
    total = int(row.runs_24h or 0)
    ok_24h = max(0, total - int(row.failed_24h or 0))
    return {
        "active_automations": int(row.active or 0),
        "needs_attention": int(row.failed_24h or 0),
        "runs_today": total,
        "success_rate_24h": round(ok_24h / total * 100, 1) if total else 0.0,
        "success_rate_30d": 0.0,
        "external_calls_24h": int(ext_calls_24h or 0),
        "marketplace_spend_24h": float(spend or 0),
        "runs_30d": int(row.runs_30d or 0),
    }

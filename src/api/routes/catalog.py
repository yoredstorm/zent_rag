# =============================================================================
# Catalog Routes — Discovery Engine & Semantic Catalog (FASE 24)
# =============================================================================
# Coherente con la API existente (org-scoped, 404 cross-tenant, RBAC). La
# cadena de ACL aplica: Connector ACL -> Discovery ACL -> Catalog ACL.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.deps import (
    get_catalog_store,
    get_connector_repo,
    get_intelligence_store,
    get_job_repo,
)
from src.catalog.authority import AuthorityService
from src.catalog.glossary import GlossaryService
from src.catalog.lineage import LineageService
from src.catalog.metrics import MetricsService
from src.catalog.readiness import ReadinessService
from src.catalog.store import PostgresCatalogStore
from src.catalog.suggestions import ReviewQueueService
from src.infrastructure.observability.logging_config import get_logger
from src.platform.rbac.policy import require_permission

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])

_SCAN_TYPES = {"initial", "incremental", "manual", "scheduled"}
_VALID_SUGGESTION_STATUS = {"pending", "approved", "rejected", "deferred", "edited_approved"}
_VALID_DATA_TYPES = {"metric", "dimension", "concept", "status_value"}
_VALID_GLOSSARY_STATUS = {"draft", "approved", "deprecated"}


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


class DiscoveryStartBody(BaseModel):
    connector_id: UUID
    kb_source_id: UUID | None = None
    scan_type: str = "initial"
    scan_interval_hours: int = Field(default=0, ge=0, le=720)

    @classmethod
    def validate_scan_type(cls, value: str) -> str:
        if value not in _SCAN_TYPES:
            raise ValueError(f"scan_type debe ser uno de {sorted(_SCAN_TYPES)}")
        return value


class EntityBody(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    display_name: str = Field(default="", max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    mapped_table_id: UUID | None = None
    status: str = "draft"


class FieldBody(BaseModel):
    entity_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    mapped_column_id: UUID | None = None
    status: str = "draft"


class GlossaryBody(BaseModel):
    concept: str = Field(min_length=1, max_length=160)
    definition: str = Field(min_length=1, max_length=8000)
    expression: str | None = Field(default=None, max_length=4000)
    data_type: str = "concept"
    status: str = "approved"
    authoritative_source_id: str | None = Field(default=None, max_length=120)
    synonyms: list[str] = Field(default_factory=list)
    owner: str | None = Field(default=None, max_length=120)
    effective_from: str | None = None
    effective_to: str | None = None


class MetricBody(BaseModel):
    metric_key: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    definition: str = Field(min_length=1, max_length=8000)
    formula: str | None = Field(default=None, max_length=4000)
    semantic_dependencies: list[str] = Field(default_factory=list)
    physical_mappings: list[dict] = Field(default_factory=list)
    filters: list[dict] = Field(default_factory=list)
    time_semantics: str | None = Field(default=None, max_length=40)
    currency_semantics: str | None = Field(default=None, max_length=40)
    owner: str | None = Field(default=None, max_length=120)
    status: str = "draft"


class AuthorityBody(BaseModel):
    domain: str = "general"
    concept: str = Field(min_length=1, max_length=160)
    source_name: str = Field(min_length=1, max_length=200)
    source_type: str = "connector"
    authority_level: str = "authoritative"
    priority: int = Field(default=1, ge=0, le=100)


# ------------------------------------------------------------------ discovery
@router.post(
    "/discovery",
    status_code=201,
    summary="Inicia un scan de discovery sobre un connector SQL",
)
async def start_discovery(
    body: DiscoveryStartBody,
    request: Request,
    connector_repo=Depends(get_connector_repo),
    job_repo=Depends(get_job_repo),
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "connectors:read")  # ACL del connector
    require_permission(request, "catalog:write")  # ACL del catálogo
    org = _org(request)
    connector = await connector_repo.get_connector(org, body.connector_id)
    if connector is None:
        raise HTTPException(404, "Connector not found")
    if "discover" not in _connector_capabilities(connector.type):
        raise HTTPException(400, f"Connector type '{connector.type}' no soporta discovery")

    from src.catalog.jobs import start_discovery_scan

    result = await start_discovery_scan(
        job_repo=job_repo,
        catalog_store=catalog_store,
        organization_id=org,
        connector_id=body.connector_id,
        kb_source_id=body.kb_source_id,
        scan_type=body.scan_type,
        scan_interval_hours=body.scan_interval_hours,
    )
    return result


def _connector_capabilities(connector_type: str) -> set[str]:
    try:
        from src.connectors.plugin.registry import get_plugin_class

        return set(get_plugin_class(connector_type).capabilities)
    except Exception:  # noqa: BLE001
        return set()


@router.get("/sources", summary="Fuentes de catálogo (por connector)")
async def list_catalog_sources(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> list[dict]:
    require_permission(request, "catalog:read")
    from src.platform.workspaces.context import resolve_workspace

    ws = await resolve_workspace(request)
    return await catalog_store.list_sources(_org(request), workspace_id=ws.id)


@router.get("/sources/{source_id}", summary="Detalle de fuente de catálogo")
async def get_catalog_source(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:read")
    source = await catalog_store.get_source(_org(request), source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    return source


@router.get("/sources/{source_id}/readiness", summary="Context Readiness por fuente")
async def source_readiness(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    readiness = await ReadinessService(
        catalog_store, intelligence_store=intelligence_store
    ).for_source(org, source_id)
    return readiness.to_dict()


@router.get("/sources/{source_id}/health", summary="Source Health (FASE 25)")
async def source_health(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")

    readiness = await ReadinessService(
        catalog_store, intelligence_store=intelligence_store
    ).for_source(org, source_id)

    failed_queries_7d = 0
    connectivity = "unknown"
    try:
        from sqlalchemy import text

        from src.infrastructure.postgres.session import get_async_session

        session = await get_async_session()
        try:
            row = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM sql_audit_logs "
                        "WHERE organization_id = :oid AND status = 'execution_error' "
                        "AND created_at >= now() - interval '7 days'"
                    ),
                    {"oid": org},
                )
            ).fetchone()
            failed_queries_7d = int(row[0] or 0) if row else 0
        finally:
            await session.close()
        connectivity = (
            "healthy"
            if source.get("phase") in ("COMPLETED", "WAITING_REVIEW")
            and source.get("scan_error") is None
            else (
                "degraded"
                if source.get("phase") in ("PARTIAL", "FAILED")
                else "unknown"
            )
        )
    except Exception:  # noqa: BLE001
        pass

    r = readiness.to_dict()
    suggested_rels = await catalog_store.list_relationships(
        org, source_id, status="suggested", limit=1000
    )
    return {
        "source_id": str(source_id),
        "phase": source.get("phase"),
        "connectivity": connectivity,
        "freshness": r["freshness"],
        "schema_coverage": r["schema_coverage"],
        "semantic_coverage": r["semantic_mapping_coverage"],
        "metric_coverage": r["metric_coverage"],
        "unknown_codes": r["unknown_code_count"],
        "pending_relationships": len(suggested_rels),
        "context_gaps": r["unknown_code_count"],
        "failed_queries_7d": failed_queries_7d,
    }


@router.get(
    "/sources/{source_id}/dependency-impact",
    summary="Knowledge Dependency Impact (FASE 25)",
)
async def source_dependency_impact(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    from src.api.deps import get_revocation_service

    return await get_revocation_service().assess(
        org, UUID(source["connector_id"])
    )


@router.get("/sources/{source_id}/scans", summary="Historial de scans + drift")
async def source_scans(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await catalog_store.list_scans(_org(request), source_id, limit=limit, offset=offset)


@router.post("/sources/{source_id}/rescan", summary="Rescan manual de una fuente")
async def rescan_source(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    job_repo=Depends(get_job_repo),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    from src.catalog.jobs import start_discovery_scan

    return await start_discovery_scan(
        job_repo=job_repo,
        catalog_store=catalog_store,
        organization_id=org,
        connector_id=UUID(source["connector_id"]),
        kb_source_id=(
            UUID(source["kb_source_id"]) if source.get("kb_source_id") else None
        ),
        scan_type="manual",
        scan_interval_hours=source.get("scan_interval_hours") or 0,
    )


# ------------------------------------------------------------------ catálogo físico
@router.get("/sources/{source_id}/tables", summary="Browse de tablas del catálogo")
async def list_tables(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await catalog_store.list_tables(
        _org(request), source_id, limit=limit, offset=offset
    )


@router.get("/tables/{table_id}", summary="Detalle de tabla con columnas")
async def get_table_detail(
    table_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    table = await catalog_store.get_table(org, table_id)
    if table is None:
        raise HTTPException(404, "Table not found")
    table["columns"] = await catalog_store.list_columns(org, table_id)
    table["enum_values"] = {}
    for col in table["columns"]:
        values = await catalog_store.list_enum_values(org, UUID(col["id"]))
        if values:
            table["enum_values"][col["column_name"]] = values
    return table


# -------------------------------------------------------------- entidades (semántico)
@router.get("/entities", summary="Business Entities")
async def list_entities(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await catalog_store.list_entities(_org(request), limit=limit, offset=offset)


@router.post("/entities", status_code=201, summary="Crea/actualiza una entidad")
async def upsert_entity(
    body: EntityBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    from src.core.domain.catalog import CatalogEntity, CatalogProvenance

    entity = CatalogEntity(
        organization_id=org,
        name=body.name.strip().lower(),
        display_name=body.display_name or body.name,
        description=body.description,
        provenance=CatalogProvenance.APPROVED
        if body.status == "approved"
        else CatalogProvenance.INFERRED,
        confidence="high" if body.status == "approved" else "low",
        evidence=["revisión manual"] if body.status == "approved" else [],
        mapped_table_id=body.mapped_table_id,
        status=body.status,
        created_by=_user(request),
        approved_by=_user(request) if body.status == "approved" else None,
    )
    await catalog_store.upsert_entity(entity)
    return (await catalog_store.get_entity(org, entity.id)) or {}


@router.get("/entities/{entity_id}/fields", summary="Business Fields de una entidad")
async def list_entity_fields(
    entity_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> list[dict]:
    require_permission(request, "catalog:read")
    org = _org(request)
    entity = await catalog_store.get_entity(org, entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    return await catalog_store.list_fields(org, entity_id)


@router.post("/entities/{entity_id}/fields", status_code=201, summary="Crea un campo")
async def upsert_field(
    entity_id: UUID,
    body: FieldBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    entity = await catalog_store.get_entity(org, entity_id)
    if entity is None:
        raise HTTPException(404, "Entity not found")
    from src.core.domain.catalog import CatalogField, CatalogProvenance

    field = CatalogField(
        organization_id=org,
        entity_id=entity_id,
        name=body.name.strip().lower(),
        description=body.description,
        provenance=CatalogProvenance.APPROVED
        if body.status == "approved"
        else CatalogProvenance.INFERRED,
        confidence="high" if body.status == "approved" else "low",
        mapped_column_id=body.mapped_column_id,
        status=body.status,
        created_by=_user(request),
        approved_by=_user(request) if body.status == "approved" else None,
    )
    await catalog_store.upsert_field(field)
    if body.mapped_column_id:
        lineage = LineageService(catalog_store)
        await lineage.record_field_mapping(
            organization_id=org, field_id=field.id, column_id=body.mapped_column_id
        )
    return {"id": str(field.id), "entity_id": str(entity_id), "name": field.name}


# ------------------------------------------------------------------- glosario
@router.get("/glossary", summary="Business Glossary (términos gobernados)")
async def list_glossary(
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    service = GlossaryService(intelligence_store)
    return await service.list(_org(request), status=status, limit=limit, offset=offset)


@router.post("/glossary", status_code=201, summary="Upsert de término del glosario")
async def upsert_glossary_term(
    body: GlossaryBody,
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    if body.data_type not in _VALID_DATA_TYPES:
        raise HTTPException(400, f"data_type debe ser uno de {sorted(_VALID_DATA_TYPES)}")
    if body.status not in _VALID_GLOSSARY_STATUS:
        raise HTTPException(400, f"status debe ser uno de {sorted(_VALID_GLOSSARY_STATUS)}")
    service = GlossaryService(intelligence_store)
    return await service.upsert(
        organization_id=org,
        concept=body.concept,
        definition=body.definition,
        expression=body.expression,
        data_type=body.data_type,
        status=body.status,
        authoritative_source_id=body.authoritative_source_id,
        created_by=_user(request),
        synonyms=body.synonyms,
        owner=body.owner,
        effective_from=_parse_dt(body.effective_from),
        effective_to=_parse_dt(body.effective_to),
    )


@router.post("/glossary/{concept}/approve", summary="Aprueba un término del glosario")
async def approve_glossary_term(
    concept: str,
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await GlossaryService(intelligence_store).approve(
        organization_id=org, concept=concept.strip().lower(), approved_by=_user(request)
    )
    if result is None:
        raise HTTPException(404, "Glossary term not found")
    try:
        from src.api.deps import get_approval_service

        await get_approval_service().record_and_maybe_replay(
            organization_id=org,
            knowledge_type="glossary",
            knowledge_id=result["concept"],
            acted_by=_user(request),
            reason="glossary term approved",
            source_evidence=["approval endpoint"],
            previous_version={"version": max(result["version"] - 1, 1)},
            new_version={"version": result["version"], "status": result["status"]},
        )
    except Exception:  # noqa: BLE001
        pass
    return result


@router.delete("/glossary/{concept}", summary="Elimina un término del glosario")
async def delete_glossary_term(
    concept: str,
    request: Request,
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    deleted = await GlossaryService(intelligence_store).delete(
        _org(request), concept.strip().lower()
    )
    if not deleted:
        raise HTTPException(404, "Glossary term not found")
    return {"deleted": concept.strip().lower()}


# ------------------------------------------------------------------- métricas
@router.get("/metrics", summary="Business Metrics gobernadas")
async def list_metrics(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await MetricsService(
        catalog_store, intelligence_store=intelligence_store
    ).list(_org(request), status=status, limit=limit, offset=offset)


@router.post("/metrics", status_code=201, summary="Upsert de una métrica")
async def upsert_metric(
    body: MetricBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    return await MetricsService(
        catalog_store, intelligence_store=intelligence_store
    ).upsert(
        organization_id=_org(request),
        metric_key=body.metric_key,
        name=body.name,
        definition=body.definition,
        formula=body.formula,
        semantic_dependencies=body.semantic_dependencies,
        physical_mappings=body.physical_mappings,
        filters=body.filters,
        time_semantics=body.time_semantics,
        currency_semantics=body.currency_semantics,
        owner=body.owner,
        status=body.status,
        created_by=_user(request),
    )


@router.post("/metrics/{metric_id}/approve", summary="Aprueba una métrica")
async def approve_metric(
    metric_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await MetricsService(
        catalog_store, intelligence_store=intelligence_store
    ).approve(org, metric_id, approved_by=_user(request))
    if result is None:
        raise HTTPException(404, "Metric not found")
    try:
        from src.api.deps import get_approval_service

        await get_approval_service().record_and_maybe_replay(
            organization_id=org,
            knowledge_type="metric",
            knowledge_id=str(metric_id),
            acted_by=_user(request),
            reason="metric approved",
            source_evidence=["approval endpoint"],
            new_version={"metric_key": result.get("metric_key"), "version": result.get("version")},
        )
    except Exception:  # noqa: BLE001
        pass
    return result


# ---------------------------------------------------------------- relaciones
@router.get("/relationships", summary="Relaciones físicas e inferidas")
async def list_relationships(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    source_id: UUID | None = None,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    org = _org(request)
    sources = [source_id] if source_id else [
        UUID(s["id"]) for s in await catalog_store.list_sources(org)
    ]
    out: list[dict] = []
    for sid in sources:
        out.extend(
            await catalog_store.list_relationships(
                org, sid, status=status, limit=limit, offset=offset
            )
        )
    return out


@router.post("/relationships/{rel_id}/confirm", summary="Confirma una relación")
async def confirm_relationship(
    rel_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    ok = await catalog_store.update_relationship_status(
        org,
        rel_id,
        status="confirmed",
        provenance="APPROVED",
        reviewed_by=_user(request),
    )
    if not ok:
        raise HTTPException(404, "Relationship not found")
    from src.infrastructure.observability.metrics import (
        rag_approved_relationships_total,
    )

    rag_approved_relationships_total.labels(organization_id=str(org)).inc()
    try:
        from src.api.deps import get_approval_service

        await get_approval_service().record(
            organization_id=org,
            knowledge_type="relationship",
            knowledge_id=str(rel_id),
            action="approve",
            acted_by=_user(request),
            reason="relationship confirmed",
        )
    except Exception:  # noqa: BLE001
        pass
    return {"confirmed": str(rel_id)}


@router.post("/relationships/{rel_id}/reject", summary="Rechaza una relación")
async def reject_relationship(
    rel_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    ok = await catalog_store.update_relationship_status(
        _org(request), rel_id, status="rejected", reviewed_by=_user(request)
    )
    if not ok:
        raise HTTPException(404, "Relationship not found")
    return {"rejected": str(rel_id)}


# ------------------------------------------------------------------ autoridad
@router.get("/authority", summary="Fuentes autoritativas por concepto")
async def list_authority(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await AuthorityService(catalog_store).list(_org(request))


@router.post("/authority", status_code=201, summary="Registra una fuente autoritativa")
async def upsert_authority(
    body: AuthorityBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await AuthorityService(catalog_store).upsert(
        organization_id=org,
        domain=body.domain,
        concept=body.concept,
        source_name=body.source_name,
        source_type=body.source_type,
        authority_level=body.authority_level,
        priority=body.priority,
        created_by=_user(request),
    )
    try:
        from src.api.deps import get_approval_service

        await get_approval_service().record(
            organization_id=org,
            knowledge_type="authority",
            knowledge_id=result.get("concept") or body.concept,
            action="approve",
            acted_by=_user(request),
            reason="source authority configured",
            new_version={"source_name": body.source_name, "level": body.authority_level},
        )
    except Exception:  # noqa: BLE001
        pass
    return result


# ----------------------------------------------------------------- sugerencias
@router.get("/suggestions", summary="Review Queue de sugerencias semánticas")
async def list_suggestions(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
    status: str | None = None,
    type: str | None = None,  # noqa: A002
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await ReviewQueueService(
        catalog_store, intelligence_store=intelligence_store
    ).list(_org(request), status=status, type=type, limit=limit, offset=offset)


class ApproveSuggestionBody(BaseModel):
    payload: dict | None = None  # EDIT_AND_APPROVE: payload editado (p.ej. meaning)


@router.post("/suggestions/{suggestion_id}/approve", summary="Aprueba una sugerencia")
async def approve_suggestion(
    suggestion_id: UUID,
    body: ApproveSuggestionBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await ReviewQueueService(
        catalog_store, intelligence_store=intelligence_store
    ).approve(org, suggestion_id, reviewed_by=_user(request), edited_payload=body.payload)
    if result is None:
        raise HTTPException(404, "Suggestion not found or not pending")
    from src.infrastructure.observability.metrics import (
        rag_semantic_approvals_total,
        rag_semantic_suggestions_approved_total,
    )

    rag_semantic_suggestions_approved_total.labels(organization_id=str(org)).inc()
    rag_semantic_approvals_total.labels(
        organization_id=str(org), knowledge_type=result["type"]
    ).inc()
    await _record_approval_from_suggestion(request, org, result, "approve")
    return result


@router.put(
    "/suggestions/{suggestion_id}/edit-approve",
    summary="EDIT_AND_APPROVE (payload editado)",
)
async def edit_approve_suggestion(
    suggestion_id: UUID,
    body: ApproveSuggestionBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    if not body.payload:
        raise HTTPException(400, "edit-approve requiere payload")
    result = await ReviewQueueService(
        catalog_store, intelligence_store=intelligence_store
    ).approve(org, suggestion_id, reviewed_by=_user(request), edited_payload=body.payload)
    if result is None:
        raise HTTPException(404, "Suggestion not found or not pending")
    return result


@router.post("/suggestions/{suggestion_id}/reject", summary="Rechaza una sugerencia")
async def reject_suggestion(
    suggestion_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await ReviewQueueService(
        catalog_store, intelligence_store=intelligence_store
    ).reject(org, suggestion_id, reviewed_by=_user(request))
    if result is None:
        raise HTTPException(404, "Suggestion not found or not pending")
    from src.infrastructure.observability.metrics import (
        rag_semantic_rejections_total,
    )

    rag_semantic_rejections_total.labels(organization_id=str(org)).inc()
    await _record_approval_from_suggestion(request, org, result, "reject")
    return result


@router.post("/suggestions/{suggestion_id}/defer", summary="Difiere una sugerencia")
async def defer_suggestion(
    suggestion_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    intelligence_store=Depends(get_intelligence_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    result = await ReviewQueueService(
        catalog_store, intelligence_store=intelligence_store
    ).defer(org, suggestion_id, reviewed_by=_user(request))
    if result is None:
        raise HTTPException(404, "Suggestion not found or not pending")
    return result


# ------------------------------------------------------------ enums / lineage
@router.get("/enums", summary="Columnas categóricas con sus valores")
async def list_enums(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    source_id: UUID | None = None,
) -> list[dict]:
    require_permission(request, "catalog:read")
    org = _org(request)
    sources = [source_id] if source_id else [
        UUID(s["id"]) for s in await catalog_store.list_sources(org)
    ]
    out: list[dict] = []
    for sid in sources:
        for table in await catalog_store.list_tables(org, sid, limit=1000):
            for col in await catalog_store.list_columns(org, UUID(table["id"])):
                values = await catalog_store.list_enum_values(org, UUID(col["id"]))
                if values:
                    out.append(
                        {
                            "source_id": str(sid),
                            "table": table["qualified_name"],
                            "column_id": col["id"],
                            "column": col["column_name"],
                            "values": values,
                        }
                    )
    return out


@router.get("/lineage", summary="Lineage / Enterprise Context Graph")
async def list_lineage(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    object_type: str | None = None,
    object_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    require_permission(request, "catalog:read")
    return await LineageService(catalog_store).list(
        _org(request), object_type=object_type, object_id=object_id, limit=limit
    )


async def _record_approval_from_suggestion(
    request: Request, org: UUID, suggestion: dict, action: str
) -> None:
    """Registra la aprobación/rechazo (who/when/why/evidencia) + replay crítico."""
    try:
        from src.api.deps import get_approval_service

        stype = suggestion["type"]
        knowledge_type = {
            "glossary_term": "glossary",
            "metric_proposal": "metric",
            "enum_definition": "enum",
            "entity_identification": "entity",
            "field_mapping": "field",
            "relationship_candidate": "relationship",
        }.get(stype, stype)
        await get_approval_service().record_and_maybe_replay(
            organization_id=org,
            knowledge_type=knowledge_type,
            knowledge_id=(
                str(suggestion["payload"].get("entity_id"))
                or str(suggestion["payload"].get("concept"))
                or suggestion["id"]
            ),
            acted_by=_user(request),
            reason=f"suggestion {action} via review queue",
            source_evidence=suggestion.get("evidence") or [],
            new_version={"suggestion": suggestion["id"], "payload": suggestion.get("payload")},
        )
    except Exception:  # noqa: BLE001
        pass


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class StudioReviewBody(BaseModel):
    action: str = Field(pattern="^(confirm|change|reject|ignore)$")
    payload: dict | None = None


class StudioFieldCreateBody(BaseModel):
    entity_id: UUID | None = None
    entity_name: str | None = Field(default=None, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    mapped_column_id: UUID | None = None
    role: str = "UNKNOWN"


class StudioFreeTextBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    column_id: UUID | None = None


class StudioBulkBody(BaseModel):
    suggestion_ids: list[UUID]
    action: str = "approve"


class LexiconBody(BaseModel):
    token: str = Field(min_length=1, max_length=80)
    meaning: str = Field(min_length=1, max_length=160)
    role: str = "UNKNOWN"
    status: str = Field(default="signal", pattern="^(signal|approved)$")


class EnumMeaningBody(BaseModel):
    meaning: str = Field(min_length=1, max_length=400)


class VerifiedDraftBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    sql: str = Field(min_length=1, max_length=8000)
    name: str | None = Field(default=None, max_length=160)


async def _studio_audit(request: Request, org: UUID, action: str, knowledge_id: str, payload: dict) -> None:
    try:
        from src.api.deps import get_approval_service
        from src.core.domain.learning import ApprovalAction

        await get_approval_service().record(
            organization_id=org,
            knowledge_type="field",
            knowledge_id=knowledge_id,
            action=ApprovalAction.APPROVE,
            acted_by=_user(request),
            reason=f"catalog.mapping.{action}",
            source_evidence=["studio"],
            new_version=payload,
        )
    except Exception:  # noqa: BLE001
        logger.warning("catalog.mapping audit failed", action=action)


@router.get("/studio/{source_id}", summary="Mapping Studio: árbol de tablas y grupos")
async def studio_tree(
    source_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
    q: str = "",
    limit: int = 80,
    offset: int = 0,
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    await catalog_store.ensure_tables()
    source = await catalog_store.get_source(org, source_id)
    if source is None:
        raise HTTPException(404, "Catalog source not found")
    from src.catalog.studio import StudioService

    return await StudioService(catalog_store).tree(
        org, source_id, q=q, limit=min(limit, 200), offset=offset
    )


@router.get("/studio/tables/{table_id}", summary="Mapping Studio: detalle de tabla")
async def studio_table(
    table_id: UUID,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:read")
    org = _org(request)
    from src.catalog.studio import StudioService

    detail = await StudioService(catalog_store).table_detail(org, table_id)
    if detail is None:
        raise HTTPException(404, "Table not found")
    return detail


@router.post("/studio/fields/{field_id}/review", summary="Confirmar / cambiar / rechazar mapping")
async def studio_review_field(
    field_id: UUID,
    body: StudioReviewBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    from src.catalog.studio import StudioService

    result = await StudioService(catalog_store).review_field(
        org, field_id, action=body.action, payload=body.payload, reviewed_by=_user(request)
    )
    if result is None:
        raise HTTPException(404, "Field not found")
    await _studio_audit(request, org, body.action, str(field_id), body.payload or {})
    return result


@router.post("/studio/fields", status_code=201, summary="Crear campo de negocio custom")
async def studio_create_field(
    body: StudioFieldCreateBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    from src.catalog.studio import StudioService

    result = await StudioService(catalog_store).create_custom_field(
        org,
        entity_id=body.entity_id,
        entity_name=body.entity_name,
        name=body.name,
        mapped_column_id=body.mapped_column_id,
        role=body.role,
        created_by=_user(request),
    )
    await _studio_audit(request, org, "create", result["id"], body.model_dump(mode="json"))
    return result


@router.post("/studio/free-text", summary="Texto libre → draft de campo (no APPROVED)")
async def studio_free_text(
    body: StudioFreeTextBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    from src.catalog.studio import StudioService

    result = await StudioService(catalog_store).free_text_draft(
        org, body.text, column_id=body.column_id, created_by=_user(request)
    )
    await _studio_audit(request, org, "free_text", result.get("id", ""), {"text": body.text[:200]})
    return result


@router.post("/studio/bulk", summary="Aprobar mappings por IDs explícitos")
async def studio_bulk(
    body: StudioBulkBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    if not body.suggestion_ids:
        raise HTTPException(400, "suggestion_ids required")
    if body.action != "approve":
        raise HTTPException(400, "only action=approve is supported")
    org = _org(request)
    from src.catalog.studio import StudioService

    result = await StudioService(catalog_store).bulk_approve(
        org, [str(i) for i in body.suggestion_ids], reviewed_by=_user(request)
    )
    await _studio_audit(
        request, org, "bulk_approve", "bulk", {"ids": [str(i) for i in body.suggestion_ids]}
    )
    return result


@router.get("/lexicon", summary="Léxico de abreviaturas de la organización")
async def list_lexicon(
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> list[dict]:
    require_permission(request, "catalog:read")
    org = _org(request)
    await catalog_store.ensure_tables()
    return await catalog_store.list_lexicon(org)


@router.put("/lexicon", summary="Upsert token del léxico org (señal, no verdad global)")
async def put_lexicon(
    body: LexiconBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    await catalog_store.ensure_tables()
    result = await catalog_store.upsert_lexicon_entry(
        organization_id=org,
        token=body.token,
        meaning=body.meaning,
        role=body.role,
        status=body.status,
        created_by=_user(request),
    )
    await _studio_audit(request, org, "lexicon", body.token, body.model_dump())
    return result


@router.put("/enums/{value_id}", summary="Significado de un valor de enum")
async def put_enum_meaning(
    value_id: UUID,
    body: EnumMeaningBody,
    request: Request,
    catalog_store: PostgresCatalogStore = Depends(get_catalog_store),
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    existing = await catalog_store.get_enum_value(org, value_id)
    if existing is None:
        raise HTTPException(404, "Enum value not found")
    updated = await catalog_store.update_enum_meaning_by_id(
        organization_id=org,
        value_id=value_id,
        meaning=body.meaning,
        reviewed_by=_user(request),
    )
    if updated is None:
        raise HTTPException(404, "Enum value not found")
    try:
        from src.core.domain.verified_query import MappingSuggestion, MappingSuggestionStatus
        from src.intelligence.verified_query_store import PostgresVerifiedQueryStore

        col = await catalog_store.get_column(org, UUID(existing["column_id"]))
        predicate = f"{(col or {}).get('column_name', 'col')} = '{existing['value']}'"
        await PostgresVerifiedQueryStore().upsert_mapping_suggestion(
            MappingSuggestion(
                organization_id=org,
                concept=body.meaning,
                entity_type="ENUM",
                physical_predicate=predicate,
                evidence_count=1,
                evidence_sample=[existing["value"]],
                status=MappingSuggestionStatus.INFERRED,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enum mapping_suggestion skipped", error=str(exc)[:200])
    await _studio_audit(request, org, "enum", str(value_id), {"meaning": body.meaning})
    return updated


@router.post("/studio/verified-query-draft", summary="Guardar SQL de prueba como DRAFT")
async def studio_verified_draft(
    body: VerifiedDraftBody,
    request: Request,
) -> dict:
    require_permission(request, "catalog:write")
    org = _org(request)
    from src.api.deps import get_verified_query_service
    from src.core.domain.verified_query import VerifiedQueryStatus

    svc = get_verified_query_service()
    await svc.store.ensure_tables()
    item = await svc.create(
        org,
        name=body.name or body.question[:80],
        canonical_question=body.question,
        verified_sql=body.sql,
        status=VerifiedQueryStatus.DRAFT,
        approved_by=None,
    )
    await _studio_audit(request, org, "verified_draft", str(item.id), {"question": body.question})
    return item.to_dict() if hasattr(item, "to_dict") else {"id": str(item.id), "status": "DRAFT"}

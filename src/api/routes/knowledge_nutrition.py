# =============================================================================
# Knowledge Nutrition — API (enrichment, acceptance, score, acciones)
# =============================================================================
# Expone lo mínimo para operar el pipeline sin UI nueva:
#   - reporte de enrichment / fingerprint
#   - acceptance: últimas corridas + probes fallidos
#   - re-evaluación sin re-ingerir
#   - nutrition score + acciones
#   - ingreso de señales de feedback -> acción
#
# Sigue los patrones existentes: require_permission + stores Postgres scoped.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.deps import get_embedding_provider, get_vector_store
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.acceptance import PostgresAcceptanceStore, evaluate_probes
from src.knowledge.acceptance.contracts import RetrievalProbe
from src.knowledge.acceptance.store import probe_from_row
from src.knowledge.nutrition import (
    FailureSignals,
    PostgresNutritionStore,
    apply_feedback_nutrition,
)
from src.knowledge.semantic import PostgresSemanticIngestionStore

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/knowledge", tags=["Knowledge Nutrition"])


class ReevaluateRequest(BaseModel):
    document_id: UUID
    max_probes: int = Field(default=50, ge=1, le=500)
    min_recall_at_5: float = Field(default=0.6, ge=0.0, le=1.0)


class FeedbackSignalsRequest(BaseModel):
    query: str = Field(default="", max_length=2000)
    retrieved_chunks: int = Field(default=0, ge=0)
    top_score: float | None = None
    evidence_used: int = Field(default=0, ge=0)
    citations: int = Field(default=0, ge=0)
    answer_gate: str | None = Field(default=None, max_length=40)
    planner_path: str | None = Field(default=None, max_length=80)
    feedback_rating: str | None = Field(default=None, max_length=10)
    feedback_reason: str | None = Field(default=None, max_length=40)
    lexical_hit: bool | None = None
    semantic_hit: bool | None = None
    wrong_source: bool | None = None
    acl_filtered: bool | None = None
    temporal_mismatch: bool | None = None
    stale: bool | None = None
    conflict: bool | None = None
    entity_unresolved: bool | None = None
    parser_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    reconstruction_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    source_id: UUID | None = None
    document_id: UUID | None = None


def _probe_from_row(row: dict) -> RetrievalProbe:
    """Compat: el converter vive en el store (reutilizado por CLI/API)."""
    return probe_from_row(row)


@router.get("/nutrition/score", summary="Nutrition score por documento")
async def nutrition_score(
    request: Request,
    document_id: UUID,
    scope: str = Query(default="document", max_length=30),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresNutritionStore()
    state = await store.get_state(
        ctx.organization_id, scope=scope, document_id=document_id
    )
    if state is None:
        raise HTTPException(status_code=404, detail="nutrition state not found")
    return state


@router.get("/nutrition/actions", summary="Acciones de nutrition")
async def nutrition_actions(
    request: Request,
    document_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresNutritionStore()
    actions = await store.list_actions(
        ctx.organization_id, document_id=document_id, status=status, limit=limit
    )
    return {"actions": actions, "count": len(actions)}


@router.get("/retrieval-acceptance", summary="Últimas evaluaciones de acceptance")
async def retrieval_acceptance(
    request: Request,
    document_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresAcceptanceStore()
    evaluations = await store.list_evaluations(
        ctx.organization_id, document_id=document_id, limit=limit
    )
    return {"evaluations": evaluations, "count": len(evaluations)}


@router.get("/retrieval-probes", summary="Probes de retrieval del documento")
async def retrieval_probes(
    request: Request,
    document_id: UUID,
    active_only: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresAcceptanceStore()
    probes = await store.list_probes(
        ctx.organization_id, document_id=document_id, active_only=active_only, limit=limit
    )
    failed = [
        row for row in probes
        if (row.get("last_result") or {}).get("passed") is False
    ]
    return {"probes": probes, "count": len(probes), "failed": failed}


@router.post("/retrieval-acceptance/reevaluate", summary="Re-evaluar retrieval sin re-ingerir")
async def reevaluate(request: Request, body: ReevaluateRequest) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    store = PostgresAcceptanceStore()
    rows = await store.list_probes(
        ctx.organization_id,
        document_id=body.document_id,
        active_only=True,
        limit=body.max_probes,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="no active probes for document")
    probes = tuple(_probe_from_row(row) for row in rows)
    role = "admin" if ctx.is_organization_admin() else "member"
    try:
        report = await evaluate_probes(
            probes,
            embedder=get_embedding_provider(),
            vector_store=get_vector_store(),
            role=role,
            user_id=ctx.user_id,
            min_recall_at_5=body.min_recall_at_5,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Retrieval reevaluation failed", error=str(exc)[:250])
        raise HTTPException(status_code=502, detail="retrieval reevaluation failed") from exc
    await store.save_evaluation(report)
    await store.update_probe_results(report)
    return report.to_dict(include_outcomes=True)


@router.post("/nutrition/feedback", summary="Señales de un run -> acción de nutrition")
async def feedback_nutrition(request: Request, body: FeedbackSignalsRequest) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:write")
    signals = FailureSignals(
        query=body.query,
        retrieved_chunks=body.retrieved_chunks,
        top_score=body.top_score,
        evidence_used=body.evidence_used,
        citations=body.citations,
        answer_gate=body.answer_gate,
        planner_path=body.planner_path,
        feedback_rating=body.feedback_rating,
        feedback_reason=body.feedback_reason,
        lexical_hit=body.lexical_hit,
        semantic_hit=body.semantic_hit,
        wrong_source=body.wrong_source,
        acl_filtered=body.acl_filtered,
        temporal_mismatch=body.temporal_mismatch,
        stale=body.stale,
        conflict=body.conflict,
        entity_unresolved=body.entity_unresolved,
        parser_quality=body.parser_quality,
        reconstruction_quality=body.reconstruction_quality,
        source_id=str(body.source_id) if body.source_id else None,
        document_id=str(body.document_id) if body.document_id else None,
    )
    outcome = await apply_feedback_nutrition(signals, organization_id=ctx.organization_id)
    return outcome.to_dict()


# ---------------------------------------------------------------------------
# Progressive Semantic Ingestion (Fases 1-2): cobertura + ventanas
# ---------------------------------------------------------------------------


@router.get(
    "/semantic-ingestion/manifests",
    summary="Manifiestos de cobertura de ingesta por fuente",
)
async def semantic_ingestion_manifests(
    request: Request,
    source_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    manifests = await store.list_manifests(
        ctx.organization_id, source_id=source_id, limit=limit
    )
    return {
        "manifests": [manifest.to_dict() for manifest in manifests],
        "count": len(manifests),
    }


@router.get(
    "/semantic-ingestion/manifest",
    summary="Manifiesto de un documento: ¿ZENT procesó toda la fuente?",
)
async def semantic_ingestion_manifest(
    request: Request,
    source_id: UUID,
    external_id: str = Query(min_length=1, max_length=512),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    manifest = await store.get_manifest(
        ctx.organization_id, source_id=source_id, external_id=external_id
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail="ingestion manifest not found")
    return manifest.to_dict()


@router.get(
    "/semantic-ingestion/coverage",
    summary="Cobertura agregada de una fuente (documentos completos/parciales)",
)
async def semantic_ingestion_coverage(
    request: Request,
    source_id: UUID | None = None,
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    return await store.coverage_summary(ctx.organization_id, source_id=source_id)


@router.get(
    "/semantic-ingestion/windows",
    summary="Ventanas semánticas planificadas de un documento",
)
async def semantic_ingestion_windows(
    request: Request,
    document_id: UUID,
    limit: int = Query(default=2000, ge=1, le=5000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    windows = await store.list_windows(
        ctx.organization_id, document_id=document_id, limit=limit
    )
    return {"windows": windows, "count": len(windows)}


@router.get(
    "/semantic-ingestion/window-results",
    summary="Resultados de comprensión local por ventana (Fase 3)",
)
async def semantic_ingestion_window_results(
    request: Request,
    document_id: UUID,
    include_items: bool = False,
    limit: int = Query(default=2000, ge=1, le=5000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    results = await store.list_window_results(
        ctx.organization_id,
        document_id=document_id,
        limit=limit,
        include_items=include_items,
    )
    return {"results": results, "count": len(results)}


@router.get(
    "/semantic-ingestion/window-state",
    summary="SemanticState de una ventana (glosario, símbolos, threads abiertos)",
)
async def semantic_ingestion_window_state(
    request: Request,
    document_id: UUID,
    window_index: int | None = None,
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    if window_index is None:
        state = await store.latest_state(ctx.organization_id, document_id=document_id)
    else:
        state = await store.get_state(
            ctx.organization_id, document_id=document_id, window_index=window_index
        )
    if state is None:
        raise HTTPException(status_code=404, detail="semantic state not found")
    return state.to_dict()


@router.get(
    "/semantic-ingestion/threads",
    summary="SemanticThreads durables de un documento (continuidad bidireccional)",
)
async def semantic_ingestion_threads(
    request: Request,
    document_id: UUID,
    status: str | None = Query(default=None, max_length=20),
    thread_type: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=5000, ge=1, le=10000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    threads = await store.list_threads(
        ctx.organization_id,
        document_id=document_id,
        status=status,
        thread_type=thread_type,
        limit=limit,
    )
    return {
        "threads": [thread.to_dict() for thread in threads],
        "count": len(threads),
        "open": sum(1 for thread in threads if thread.is_open),
    }


@router.get(
    "/semantic-ingestion/units",
    summary="Unidades semánticas merged del documento (stitcher Fase 5)",
)
async def semantic_ingestion_units(
    request: Request,
    document_id: UUID,
    unit_kind: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    units = await store.list_units(
        ctx.organization_id,
        document_id=document_id,
        unit_kind=unit_kind,
        limit=limit,
    )
    return {"units": units, "count": len(units)}


@router.get(
    "/semantic-ingestion/relations",
    summary="Relaciones semánticas tipadas del documento (stitcher Fase 5)",
)
async def semantic_ingestion_relations(
    request: Request,
    document_id: UUID,
    relation_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=10000, ge=1, le=50000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    relations = await store.list_relations(
        ctx.organization_id,
        document_id=document_id,
        relation_type=relation_type,
        limit=limit,
    )
    return {"relations": relations, "count": len(relations)}


@router.get(
    "/semantic-ingestion/regions",
    summary="Modelos regionales del documento (Fase 6)",
)
async def semantic_ingestion_regions(
    request: Request,
    document_id: UUID,
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    regions = await store.list_regional_models(
        ctx.organization_id, document_id=document_id, limit=limit
    )
    return {"regions": regions, "count": len(regions)}


@router.get(
    "/semantic-ingestion/global",
    summary="Modelo global estructurado del documento (Fase 7)",
)
async def semantic_ingestion_global(
    request: Request,
    document_id: UUID,
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    model = await store.get_global_model(
        ctx.organization_id, document_id=document_id
    )
    if model is None:
        raise HTTPException(status_code=404, detail="global model not found")
    return model


@router.get(
    "/semantic-ingestion/fabric/nodes",
    summary="Nodos del Semantic Fabric del documento (Fase 8)",
)
async def semantic_ingestion_fabric_nodes(
    request: Request,
    document_id: UUID,
    node_type: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=5000, ge=1, le=50000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    nodes = await store.list_fabric_nodes(
        ctx.organization_id,
        document_id=document_id,
        node_type=node_type,
        limit=limit,
    )
    return {"nodes": nodes, "count": len(nodes)}


@router.get(
    "/semantic-ingestion/fabric/edges",
    summary="Aristas del Semantic Fabric del documento (Fase 8)",
)
async def semantic_ingestion_fabric_edges(
    request: Request,
    document_id: UUID,
    relation_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=10000, ge=1, le=100000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    edges = await store.list_fabric_edges(
        ctx.organization_id,
        document_id=document_id,
        relation_type=relation_type,
        limit=limit,
    )
    return {"edges": edges, "count": len(edges)}


@router.get(
    "/semantic-ingestion/fabric/identities",
    summary="Candidatos de identidad cross-source (Fase 8, nunca fusiona)",
)
async def semantic_ingestion_fabric_identities(
    request: Request,
    document_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict:
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "knowledge:read")
    store = PostgresSemanticIngestionStore()
    candidates = await store.list_identity_candidates(
        ctx.organization_id,
        document_id=document_id,
        status=status,
        limit=limit,
    )
    return {"identities": candidates, "count": len(candidates)}

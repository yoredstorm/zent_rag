# =============================================================================
# Evaluation Routes — Feedback collection and quality stats
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.api.deps import get_agent_runtime, get_llm_provider, get_rag_orchestrator
from src.infrastructure.observability.logging_config import get_logger
from src.rag.evaluation.store import ensure_eval_table, get_recent, get_stats, store_feedback

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/eval", tags=["Evaluation"])


def _resolve_organization_id(request: Request, x_organization_id: str) -> UUID:
    """Organization autenticado gana; header distinto -> 403 (anti cross-organization)."""
    from src.api.security import resolve_organization

    return resolve_organization(request, x_organization_id)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class FeedbackRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    rating: str = Field(..., pattern=r"^(up|down)$")
    query_id: str | None = None
    conversation_id: str | None = None
    answer: str = Field(default="", max_length=10000)
    role: str = Field(default="admin", pattern=r"^(admin|customer)$")
    model: str = Field(default="")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    method: str = Field(default="rag")
    comment: str = Field(default="", max_length=500)
    lazy_ingested: bool = Field(default=False)


# ---------------------------------------------------------------------------
# POST /api/v1/eval/feedback
# ---------------------------------------------------------------------------


@router.post("/feedback", summary="Enviar feedback (thumbs up/down) para una respuesta RAG")
async def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    organization_id = _resolve_organization_id(request, x_organization_id)
    await ensure_eval_table()

    try:
        qid = UUID(body.query_id) if body.query_id else None
    except ValueError:
        qid = None

    try:
        cid = UUID(body.conversation_id) if body.conversation_id else None
    except ValueError:
        cid = None

    await store_feedback(
        organization_id=organization_id,
        query=body.query,
        rating=body.rating,
        query_id=qid,
        conversation_id=cid,
        answer=body.answer,
        role=body.role,
        model=body.model,
        prompt_tokens=body.prompt_tokens,
        completion_tokens=body.completion_tokens,
        total_tokens=body.total_tokens,
        latency_ms=body.latency_ms,
        method=body.method,
        comment=body.comment,
        lazy_ingested=body.lazy_ingested,
    )

    return {"status": "ok", "rating": body.rating}


# ---------------------------------------------------------------------------
# GET /api/v1/eval/stats
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Estadísticas de calidad RAG")
async def eval_stats(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    role: str | None = Query(default=None, pattern=r"^(admin|customer)$"),
    days: int = Query(default=30, ge=1, le=365),
):
    organization_id = _resolve_organization_id(request, x_organization_id)
    await ensure_eval_table()
    return await get_stats(organization_id, role=role, days=days)


# ---------------------------------------------------------------------------
# GET /api/v1/eval/recent
# ---------------------------------------------------------------------------


@router.get("/recent", summary="Evaluaciones recientes")
async def eval_recent(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
    limit: int = Query(default=20, ge=1, le=100),
):
    organization_id = _resolve_organization_id(request, x_organization_id)
    await ensure_eval_table()
    return await get_recent(organization_id, limit=limit)


@router.post("/run", summary="Ejecutar evaluación golden set (protegido)")
async def run_golden_eval(
    request: Request,
    x_organization_id: str = Header(default="", alias="X-Organization-Id"),
):
    from src.api.security import require_organization_admin, resolve_organization
    from src.core.config import get_settings
    from src.scripts.eval_rag import run_eval

    if not get_settings().RAG_ADMIN_ENABLED:
        raise HTTPException(403, "Eval run requires RAG_ADMIN_ENABLED=true")

    ctx = require_organization_admin(request)
    organization_id = resolve_organization(request, x_organization_id)
    user_id = ctx.user_id or UUID("00000000-0000-0000-0000-000000000002")

    import pathlib

    settings = get_settings()
    if settings.GOLDEN_SET_PATH:
        golden_path = pathlib.Path(settings.GOLDEN_SET_PATH)
    else:
        # Golden set por defecto: el del vertical demo (RAG_SEED_DEMO_DATA).
        golden_path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "verticals"
            / "demo_farmacia"
            / "golden"
            / "rag_farmacia.json"
        )

    summary = await run_eval(
        golden_path=golden_path,
        organization_id=organization_id,
        user_id=user_id,
    )
    return summary


# =============================================================================
# ZENT Evaluation Engine — datasets, runs y comparación de versiones
# =============================================================================
# POST   /api/v1/eval/datasets/import        Importar golden set (schema v2)
# GET    /api/v1/eval/datasets               Listar datasets
# POST   /api/v1/eval/runs                   Ejecutar un run de evaluación
# GET    /api/v1/eval/runs                   Listar runs
# GET    /api/v1/eval/runs/{run_id}          Detalle de un run (con casos)
# POST   /api/v1/eval/runs/{run_id}/compare  Regresión vs baseline
# =============================================================================


class DatasetImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    cases: list[dict] = Field(..., min_length=1, max_length=1000)
    weights: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    dataset_id: UUID
    target_type: str = Field(default="rag", pattern=r"^(rag|agent)$")
    target_id: UUID | None = None
    user_id: UUID | None = None
    judge_enabled: bool = True


class EvalCompareRequest(BaseModel):
    baseline_run_id: UUID


@router.post("/datasets/import", summary="Importar golden set (schema v2, admin org)")
async def eval_dataset_import(
    body: DatasetImportRequest,
    request: Request,
):
    from src.api.security import require_organization_admin, resolve_organization
    from src.rag.evaluation.datasets import dataset_to_payload, load_dataset
    from src.rag.evaluation.store import (
        ensure_eval_engine_tables,
        save_dataset,
    )

    ctx = require_organization_admin(request)
    organization_id = resolve_organization(request)
    dataset = load_dataset(body.cases, name=body.name)
    dataset.weights = body.weights
    dataset.metadata = body.metadata
    await ensure_eval_engine_tables()
    dataset_id = await save_dataset(
        organization_id,
        dataset.name,
        dataset_to_payload(dataset),
        schema_version=dataset.schema_version,
        weights=dataset.weights,
        metadata=dataset.metadata,
    )
    return {
        "status": "imported",
        "dataset_id": str(dataset_id),
        "name": dataset.name,
        "case_count": dataset.case_count,
    }


@router.get("/datasets", summary="Listar datasets de evaluación (admin org)")
async def eval_dataset_list(request: Request):
    from src.api.security import require_organization_admin, resolve_organization
    from src.rag.evaluation.store import ensure_eval_engine_tables, list_datasets

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_eval_engine_tables()
    return {"datasets": await list_datasets(organization_id)}


@router.post("/runs", summary="Ejecutar un run de evaluación (admin org)")
async def eval_run_create(
    body: EvalRunRequest,
    request: Request,
    orchestrator=Depends(get_rag_orchestrator),
    runtime=Depends(get_agent_runtime),
    llm_provider=Depends(get_llm_provider),
):
    from src.api.deps import (
        get_agent_repo,
        get_kb_repo,
        get_organization_repo,
    )
    from src.api.security import require_organization_admin, resolve_organization
    from src.core.config import get_settings
    from src.rag.evaluation.datasets import load_dataset
    from src.rag.evaluation.judge import LLMJudge
    from src.rag.evaluation.runner import EvalRunner
    from src.rag.evaluation.snapshot import (
        build_agent_snapshot,
        build_rag_snapshot,
        compute_version_id,
    )
    from src.rag.evaluation.store import (
        ensure_eval_engine_tables,
        get_dataset,
        save_eval_run,
    )
    from src.rag.evaluation.targets import AgentTarget, EvalTarget, RAGTarget

    settings = get_settings()
    if not settings.RAG_ADMIN_ENABLED:
        raise HTTPException(403, "Eval runs require RAG_ADMIN_ENABLED=true")

    ctx = require_organization_admin(request)
    organization_id = resolve_organization(request)
    user_id = body.user_id or ctx.user_id or UUID("00000000-0000-0000-0000-000000000002")

    await ensure_eval_engine_tables()
    dataset_row = await get_dataset(organization_id, body.dataset_id)
    if dataset_row is None:
        raise HTTPException(404, "Dataset not found")
    dataset = load_dataset(dataset_row["cases"], name=dataset_row["name"])
    dataset.weights = dataset_row.get("weights") or {}

    organization = await get_organization_repo().get_by_id(organization_id)
    if organization is None:
        raise HTTPException(404, "Organization not found")

    if body.target_type == "agent":
        if body.target_id is None:
            raise HTTPException(400, "target_id (agent_id) requerido para target agent")
        agent = await get_agent_repo().get_agent(organization_id, body.target_id)
        if agent is None:
            raise HTTPException(404, "Agent not found")
        target: EvalTarget = AgentTarget(
            runtime,
            agent,
            organization_id,
            user_id,
            org_config=organization.config_json or {},
            permissions=ctx.permissions or frozenset({"*"}),
        )
        snapshot = build_agent_snapshot(agent, organization.config_json or {})
    else:
        knowledge_base = None
        if body.target_id is not None:
            knowledge_base = await get_kb_repo().get_kb(organization_id, body.target_id)
        target = RAGTarget(
            orchestrator,
            organization_id,
            user_id,
            target_id=body.target_id,
            target_name="rag-pipeline",
        )
        snapshot = build_rag_snapshot(organization, knowledge_base)

    judge = LLMJudge(
        llm_provider,
        model=settings.EVAL_JUDGE_MODEL,
        enabled=body.judge_enabled,
    )
    runner = EvalRunner(target, judge)
    summary = await runner.run(
        dataset,
        version_snapshot=snapshot,
        version_id=compute_version_id(snapshot),
    )
    summary["dataset_id"] = str(body.dataset_id)
    await save_eval_run(organization_id, summary)

    return {k: v for k, v in summary.items() if k != "cases"}


@router.get("/runs", summary="Listar runs de evaluación (admin org)")
async def eval_run_list(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    from src.api.security import require_organization_admin, resolve_organization
    from src.rag.evaluation.store import ensure_eval_engine_tables, list_eval_runs

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_eval_engine_tables()
    return {"runs": await list_eval_runs(organization_id, limit=limit)}


@router.get("/runs/{run_id}", summary="Detalle de un run de evaluación (admin org)")
async def eval_run_detail(
    run_id: UUID,
    request: Request,
):
    from src.api.security import require_organization_admin, resolve_organization
    from src.rag.evaluation.store import ensure_eval_engine_tables, get_eval_run

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_eval_engine_tables()
    run = await get_eval_run(organization_id, run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return run


@router.post("/runs/{run_id}/compare", summary="Comparar run contra baseline (regresión)")
async def eval_run_compare(
    run_id: UUID,
    body: EvalCompareRequest,
    request: Request,
):
    from src.api.security import require_organization_admin, resolve_organization
    from src.rag.evaluation.regression import compare_runs
    from src.rag.evaluation.store import ensure_eval_engine_tables, get_eval_run

    require_organization_admin(request)
    organization_id = resolve_organization(request)
    await ensure_eval_engine_tables()
    current = await get_eval_run(organization_id, run_id)
    baseline = await get_eval_run(organization_id, body.baseline_run_id)
    if current is None:
        raise HTTPException(404, "Current run not found")
    if baseline is None:
        raise HTTPException(404, "Baseline run not found")
    return compare_runs(current, baseline)

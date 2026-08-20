# =============================================================================
# Evaluation Routes — Feedback collection and quality stats
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

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

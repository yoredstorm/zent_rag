# =============================================================================
# Evaluation Routes — Feedback collection and quality stats
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.infrastructure.evaluation import ensure_eval_table, get_recent, get_stats, store_feedback
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/eval", tags=["Evaluation"])


def _resolve_tenant_id(request: Request, x_tenant_id: str) -> UUID:
    tid = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tid:
        raise HTTPException(400, "X-Tenant-Id header required")
    try:
        return UUID(tid)
    except ValueError:
        raise HTTPException(400, "X-Tenant-Id must be a valid UUID")


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


# ---------------------------------------------------------------------------
# POST /api/v1/eval/feedback
# ---------------------------------------------------------------------------


@router.post("/feedback", summary="Enviar feedback (thumbs up/down) para una respuesta RAG")
async def submit_feedback(
    body: FeedbackRequest,
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
):
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
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
        tenant_id=tenant_id,
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
    )

    return {"status": "ok", "rating": body.rating}


# ---------------------------------------------------------------------------
# GET /api/v1/eval/stats
# ---------------------------------------------------------------------------


@router.get("/stats", summary="Estadísticas de calidad RAG")
async def eval_stats(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    role: str | None = Query(default=None, pattern=r"^(admin|customer)$"),
    days: int = Query(default=30, ge=1, le=365),
):
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    await ensure_eval_table()
    return await get_stats(tenant_id, role=role, days=days)


# ---------------------------------------------------------------------------
# GET /api/v1/eval/recent
# ---------------------------------------------------------------------------


@router.get("/recent", summary="Evaluaciones recientes")
async def eval_recent(
    request: Request,
    x_tenant_id: str = Header(default="", alias="X-Tenant-Id"),
    limit: int = Query(default=20, ge=1, le=100),
):
    tenant_id = _resolve_tenant_id(request, x_tenant_id)
    await ensure_eval_table()
    return await get_recent(tenant_id, limit=limit)

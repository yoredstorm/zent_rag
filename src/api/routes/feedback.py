# =============================================================================
# Sentiment & Feedback — submit de feedback y analytics del tenant.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/feedback", tags=["Feedback"])


@router.post("", summary="Enviar feedback de una respuesta")
async def tenant_feedback_submit(body: FeedbackIn, request: Request):
    from src.platform.feedback.feedback import submit_feedback
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await submit_feedback(
            ctx.organization_id,
            body.rating,
            agent_id=UUID(body.agent_id) if body.agent_id else None,
            deployment_id=UUID(body.deployment_id) if body.deployment_id else None,
            run_id=UUID(body.run_id) if body.run_id else None,
            trace_id=body.trace_id,
            reason=body.reason,
            comment=body.comment,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/analytics", summary="CSAT/NPS por agente")
async def tenant_feedback_analytics(request: Request, hours: int = 168):
    from src.platform.feedback.feedback import analytics
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await analytics(ctx.organization_id, None, hours)


@router.get("/trends", summary="Tendencia diaria")
async def tenant_feedback_trends(request: Request, days: int = 14):
    from src.platform.feedback.feedback import trends
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await trends(ctx.organization_id, days)


class FeedbackIn(BaseModel):
    rating: str = Field(..., pattern="^(up|down)$")
    agent_id: str | None = None
    deployment_id: str | None = None
    run_id: str | None = None
    trace_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=2000)

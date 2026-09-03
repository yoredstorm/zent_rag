# =============================================================================
# AI Chat Analytics & Conversational Insights v2.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Request

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/chat-insights", tags=["Chat Insights"])


@router.get("/funnel", summary="Embudo conversacional")
async def insights_funnel(request: Request, days: int = 30):
    from src.platform.chatinsights.insights import conversation_funnel
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await conversation_funnel(ctx.organization_id, min(max(days, 1), 90))


@router.get("/topics", summary="Temas de las consultas")
async def insights_topics(request: Request, days: int = 30):
    from src.platform.chatinsights.insights import topic_analysis
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await topic_analysis(ctx.organization_id, min(max(days, 1), 90))


@router.get("/friction", summary="Detección de fricción")
async def insights_friction(request: Request, days: int = 30):
    from src.platform.chatinsights.insights import friction_detection
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await friction_detection(ctx.organization_id, min(max(days, 1), 90))


@router.get("/channels", summary="Comparativa por canal")
async def insights_channels(request: Request, days: int = 30):
    from src.platform.chatinsights.insights import channel_comparison
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await channel_comparison(ctx.organization_id, min(max(days, 1), 90))


@router.get("/overview", summary="Overview con tendencia 7d")
async def insights_overview(request: Request, days: int = 7):
    from src.platform.chatinsights.insights import insights_overview
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await insights_overview(ctx.organization_id, min(max(days, 1), 30))

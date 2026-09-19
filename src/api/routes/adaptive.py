# =============================================================================
# Adaptive RAG Control Center status.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Request

from src.core.config import get_settings
from src.platform.rbac.authorization import require_platform_permission
from src.rag.adaptive.health import adaptive_health

router = APIRouter(prefix="/api/v1/platform/adaptive", tags=["Adaptive RAG"])


@router.get("/status", summary="Adaptive RAG status")
async def adaptive_status(request: Request) -> dict:
    require_platform_permission(request, "operations.read")
    settings = get_settings()
    health = adaptive_health()
    return {
        **health,
        "mode": settings.ADAPTIVE_RAG_MODE,
        "canary_percentage": settings.ADAPTIVE_RAG_CANARY_PERCENTAGE,
        "max_retrieval_attempts": settings.ADAPTIVE_RAG_MAX_RETRIEVAL_ATTEMPTS,
        "top_k": {
            "min": settings.ADAPTIVE_RAG_TOP_K_MIN,
            "max": settings.ADAPTIVE_RAG_TOP_K_MAX,
            "lookup": settings.ADAPTIVE_RAG_TOP_K_LOOKUP,
            "compare": settings.ADAPTIVE_RAG_TOP_K_COMPARE,
            "multi": settings.ADAPTIVE_RAG_TOP_K_MULTI,
        },
        "jev_evidence": settings.ADAPTIVE_RAG_JEV_EVIDENCE,
        "fast_path": settings.ADAPTIVE_RAG_FAST_PATH,
        "rewrite": settings.ADAPTIVE_RAG_REWRITE,
        "decision_mode": settings.DECISION_ROUTING_MODE,
        "rollout": {
            "shadow": "plan without changing retrieval",
            "canary": "percentage of requests apply the plan",
            "cutover": "compare_legacy_vs_adaptive on golden set first",
        },
    }

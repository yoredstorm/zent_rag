# =============================================================================
# Decision Engine Control Center + tenant-safe traces.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Request

from src.core.config import get_settings
from src.decision.health import decision_health
from src.decision.traces import DecisionTraceStore
from src.platform.rbac.authorization import require_platform_permission

router = APIRouter(prefix="/api/v1/platform/decision", tags=["Decision Engine"])
_store = DecisionTraceStore()


@router.get("/status", summary="Decision Engine status")
async def decision_status(request: Request) -> dict:
    require_platform_permission(request, "operations.read")
    settings = get_settings()
    health = decision_health()
    return {
        **health,
        "primary_provider": health["primary"],
        "fallback": settings.DECISION_FALLBACK_MODEL or settings.GATEWAY_CHEAP_MODEL or settings.LITELLM_DEFAULT_MODEL,
        "complex_model": settings.DECISION_COMPLEX_MODEL or settings.GATEWAY_QUALITY_MODEL,
        "mode": settings.DECISION_ROUTING_MODE,
        "shadow": settings.JEV_SHADOW_MODE,
        "high_confidence": settings.JEV_ROUTING_HIGH_CONFIDENCE,
        "low_confidence": settings.JEV_ROUTING_LOW_CONFIDENCE,
        "canary_percentage": settings.JEV_CANARY_PERCENTAGE,
        "jev_status": health["jev"],
        "jev_model": settings.JEV_MODEL,
    }


@router.get("/dashboard", summary="Decision Engine dashboard")
async def decision_dashboard(request: Request) -> dict:
    require_platform_permission(request, "analytics.read")
    return await _store.dashboard()


@router.get("/traces", summary="Recent routing decisions")
async def decision_traces(request: Request, limit: int = 50) -> dict:
    require_platform_permission(request, "analytics.read")
    rows = await _store.list_recent(None, limit=limit)
    serialized = []
    for row in rows:
        item = dict(row)
        for key in ("id", "organization_id"):
            if item.get(key) is not None:
                item[key] = str(item[key])
        created = item.get("created_at")
        if hasattr(created, "isoformat"):
            item["created_at"] = created.isoformat()
        serialized.append(item)
    return {"items": serialized}

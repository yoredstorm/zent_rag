# =============================================================================
# Decision Engine Control Center + tenant-safe traces.
# =============================================================================
# Secciones: AI Runtime (status), Decision Health, JEV usage, Model comparison,
# Routing accuracy (learning), Cost breakdown, Confidence calibration,
# Risk policy, Target selection (Judgment Fabric), Explain.
#
# Nunca se expone chain-of-thought: sólo etiquetas, confianza, costos y
# resultado de política.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from src.core.config import get_settings
from src.decision.explanation import explain_decision
from src.decision.health import decision_health
from src.decision.learning import (
    confidence_calibration,
    decision_learning_report,
    model_comparison,
)
from src.decision.risk_policy import DecisionRiskPolicy
from src.decision.selection import selection_observations
from src.decision.traces import DecisionTraceStore
from src.platform.rbac.authorization import require_platform_permission
from src.runtime.cost_breakdown import cost_breakdown, request_cost_breakdown

router = APIRouter(prefix="/api/v1/platform/decision", tags=["Decision Engine"])
_store = DecisionTraceStore()


def _org_param(request: Request) -> UUID | None:
    raw = request.query_params.get("organization_id")
    if not raw:
        return None
    try:
        return UUID(raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization_id inválido",
        ) from None


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
        "batch_mode": settings.DECISION_BATCH_MODE,
        "target_selection": settings.DECISION_TARGET_SELECTION,
        "risk_max_selectable": settings.DECISION_RISK_MAX_SELECTABLE,
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


@router.get("/learning", summary="Decision learning (routing accuracy, mismatches)")
async def decision_learning(request: Request, days: int = 30) -> dict:
    require_platform_permission(request, "analytics.read")
    return await decision_learning_report(organization_id=_org_param(request), days=days)


@router.get("/calibration", summary="Confidence calibration buckets")
async def decision_calibration(request: Request, days: int = 30) -> dict:
    require_platform_permission(request, "analytics.read")
    return await confidence_calibration(organization_id=_org_param(request), days=days)


@router.get("/models", summary="Production vs candidate model comparison")
async def decision_models(request: Request, days: int = 30) -> dict:
    require_platform_permission(request, "analytics.read")
    settings = get_settings()
    report = await model_comparison(organization_id=_org_param(request), days=days)
    return {
        **report,
        "production_model": settings.JEV_MODEL,
        "candidate_model": settings.JEV_CANARY_MODEL or None,
        "canary_percentage": settings.JEV_CANARY_PERCENTAGE,
    }


@router.get("/costs", summary="JEV/LLM cost breakdown")
async def decision_costs(request: Request, days: int = 30) -> dict:
    require_platform_permission(request, "analytics.read")
    return await cost_breakdown(organization_id=_org_param(request), days=days)


@router.get(
    "/requests/{request_id}/costs",
    summary="Per-request cost breakdown (tenant-scoped)",
)
async def decision_request_costs(
    request: Request, request_id: UUID, organization_id: UUID
) -> dict:
    require_platform_permission(request, "analytics.read")
    return await request_cost_breakdown(
        organization_id=organization_id, request_id=request_id
    )


@router.get("/risk-policy", summary="Resolved risk-aware thresholds")
async def decision_risk_policy(request: Request) -> dict:
    require_platform_permission(request, "operations.read")
    settings = get_settings()
    tenant_policy: dict = {}
    org_id = _org_param(request)
    if org_id is not None:
        try:
            from src.api.deps import get_organization_repo

            org = await get_organization_repo().get_by_id(org_id)
            config = dict(getattr(org, "config_json", None) or {})
            tenant_policy = dict(config.get("decision") or {})
        except Exception:  # noqa: BLE001 — sin org se muestran los defaults
            tenant_policy = {}
    policy = DecisionRiskPolicy.from_settings(settings, tenant_policy=tenant_policy)
    return {
        **policy.to_public_dict(),
        "max_selectable_risk": settings.DECISION_RISK_MAX_SELECTABLE,
        "tenant_override": bool(tenant_policy.get("risk_policy")),
        "note": "Los thresholds se resuelven acá; ningún módulo los hardcodea.",
    }


@router.get("/selection", summary="Judgment Fabric target selection observations")
async def decision_selection(request: Request) -> dict:
    require_platform_permission(request, "analytics.read")
    settings = get_settings()
    observations = selection_observations()
    return {
        "mode": settings.DECISION_TARGET_SELECTION,
        "observations": observations[-50:],
        "count": len(observations),
        "note": "Shadow observa sin ejecutar; on re-autoriza con la política.",
    }


@router.get("/preflight", summary="JEV preflight effectiveness (judgment before the LLM)")
async def decision_preflight(request: Request, phase: str | None = None) -> dict:
    """KPIs del juicio previo + registro de preguntas (§54, §55, §53).

    Sólo agrega lo observado: sin baseline no se calcula "costo evitado".
    """
    require_platform_permission(request, "analytics.read")
    from src.decision.preflight_report import preflight_questions, preflight_report
    from src.rag.preflight_hook import settings_from_app

    settings = settings_from_app()
    report = preflight_report(settings=settings, mode=settings.mode)
    report["registry"] = preflight_questions(phase=phase)
    report["policy"] = _preflight_policy().to_public_dict()
    return report


def _preflight_policy():
    from src.decision.confidence import default_policy

    return default_policy()


@router.get("/explain", summary="Operational explanation for a request")
async def decision_explain(
    request: Request, request_id: UUID, organization_id: UUID, mode: str = "user"
) -> dict:
    require_platform_permission(request, "analytics.read")
    row = await _store.get_by_request(organization_id, request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sin traza para ese request",
        )
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    first = results[0] if results and isinstance(results[0], dict) else {}

    class _DecisionView:
        capability = str(row.get("selected_capability") or "")
        provider = str(row.get("provider") or "")
        confidence = float(row.get("confidence") or 0.0)
        fallback_used = bool(row.get("fallback_used"))
        latency_ms = float(row.get("latency_ms") or 0.0)
        estimated_cost = float(row.get("estimated_cost") or 0.0)
        metadata = {
            "reason": first.get("reason") or row.get("routing_mode"),
            "model": payload.get("model") or "",
            "questions": [
                str(q.get("id"))
                for q in (payload.get("questions") or [])
                if isinstance(q, dict) and q.get("id")
            ],
        }

    explanation = explain_decision(_DecisionView(), mode=mode)
    return {
        "request_id": str(request_id),
        "organization_id": str(organization_id),
        "explanation": explanation,
        "trace": {
            "provider": row.get("provider"),
            "selected_capability": row.get("selected_capability"),
            "actual_capability": row.get("actual_capability"),
            "jev_capability": row.get("jev_capability"),
            "agreement": row.get("agreement"),
            "canary": row.get("canary"),
            "shadow": row.get("shadow"),
        },
    }

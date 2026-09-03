# =============================================================================
# AI Risk & Compliance Center v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/risk-center", tags=["Risk Center"])


@router.post("/assess", summary="Scoring automático de riesgos")
async def risk_assess(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import assess_organization_risks

    ctx = require_permission(request, "billing:read")
    return await assess_organization_risks(ctx.organization_id)


@router.get("/register", summary="Registro de riesgos")
async def risk_register(request: Request, status: str = "open"):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import risk_register

    ctx = require_permission(request, "billing:read")
    return await risk_register(ctx.organization_id, status)


@router.post("/risks", summary="Registrar riesgo manual")
async def risk_add(body: RiskIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import add_manual_risk

    ctx = require_permission(request, "billing:write")
    try:
        return await add_manual_risk(
            ctx.organization_id,
            body.risk_type,
            body.severity,
            body.notes,
            UUID(body.agent_id) if body.agent_id else None,
            ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/risks/{risk_id}/mitigate", summary="Mitigar riesgo")
async def risk_mitigate(risk_id: str, body: MitigateIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import mitigate_risk

    ctx = require_permission(request, "billing:write")
    result = await mitigate_risk(ctx.organization_id, UUID(risk_id), body.description, ctx.user_id)
    if result is None:
        raise HTTPException(404, "Risk not found")
    return result


@router.post("/risks/{risk_id}/accept", summary="Aceptar riesgo")
async def risk_accept(risk_id: str, body: AcceptIn, request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import accept_risk

    ctx = require_permission(request, "billing:write")
    result = await accept_risk(ctx.organization_id, UUID(risk_id), body.reason)
    if result is None:
        raise HTTPException(404, "Risk not found")
    return result


@router.get("/heatmap", summary="Heatmap de riesgos por agente")
async def risk_heatmap(request: Request):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import risk_heatmap

    ctx = require_permission(request, "billing:read")
    return await risk_heatmap(ctx.organization_id)


@router.get("/mitigations", summary="Panel de mitigaciones")
async def risk_mitigations(request: Request, limit: int = 50):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import mitigations_list

    ctx = require_permission(request, "billing:read")
    return await mitigations_list(ctx.organization_id, limit)


@router.get("/compliance/posture", summary="Postura de cumplimiento")
async def risk_posture(request: Request, framework: str = "eu_ai_act"):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import compliance_posture

    ctx = require_permission(request, "billing:read")
    return await compliance_posture(ctx.organization_id, framework)


@router.get("/compliance/trend", summary="Tendencia de postura")
async def risk_trend(request: Request, framework: str = "eu_ai_act", days: int = 30):
    from src.platform.rbac.policy import require_permission
    from src.platform.riskcenter.risk_center import posture_trend

    ctx = require_permission(request, "billing:read")
    return await posture_trend(ctx.organization_id, framework, min(max(days, 1), 90))


class RiskIn(BaseModel):
    risk_type: str
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    notes: str | None = Field(default=None, max_length=500)
    agent_id: str | None = None


class MitigateIn(BaseModel):
    description: str = Field(min_length=3, max_length=500)


class AcceptIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)

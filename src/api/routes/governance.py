# =============================================================================
# AI Governance Board & Audit Trail v2.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/governance", tags=["Governance"])


@router.get("/policies", summary="Políticas de gobierno")
async def governance_policies(request: Request):
    from src.platform.governance.board import list_policies
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_policies(ctx.organization_id)


@router.post("/policies/{policy_id}/revision", summary="Revisar política")
async def governance_policy_revision(policy_id: str, body: PolicyReviseIn, request: Request):
    from src.platform.governance.board import revise_policy
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await revise_policy(ctx.organization_id, UUID(policy_id), body.content, ctx.user_id)
    if result is None:
        raise HTTPException(404, "Policy not found")
    return result


@router.post("/decisions", summary="Crear decisión de gobierno")
async def governance_decision_create(body: DecisionIn, request: Request):
    from src.platform.governance.board import create_decision
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await create_decision(
            ctx.organization_id,
            body.decision_type,
            body.title,
            body.rationale,
            UUID(body.target_id) if body.target_id else None,
            ctx.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/decisions/{decision_id}/decide", summary="Firmar decisión")
async def governance_decision_decide(decision_id: str, body: DecideIn, request: Request):
    from src.platform.governance.board import decide
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    result = await decide(ctx.organization_id, UUID(decision_id), body.approve, ctx.user_id)
    if result is None:
        raise HTTPException(404, "Decision not found")
    return result


@router.get("/decisions", summary="Decisiones de la junta")
async def governance_decisions(request: Request, status: str | None = None):
    from src.platform.governance.board import list_decisions
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_decisions(ctx.organization_id, status)


@router.get("/audit", summary="Línea de auditoría")
async def governance_audit(request: Request, limit: int = 100):
    from src.platform.governance.board import audit_trail
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await audit_trail(ctx.organization_id, limit)


@router.post("/audit/verify", summary="Verificar integridad de la auditoría")
async def governance_audit_verify(request: Request):
    from src.platform.governance.board import verify_audit
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await verify_audit(ctx.organization_id)


@router.get("/certifications", summary="Certificaciones del equipo")
async def governance_certifications(request: Request, status: str = "valid"):
    from src.platform.governance.board import list_certifications
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await list_certifications(ctx.organization_id, status)


@router.post("/certifications", summary="Registrar certificación")
async def governance_certification_add(body: CertificationIn, request: Request):
    from src.platform.governance.board import add_certification
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await add_certification(
            ctx.organization_id, body.member_name, body.certification, body.expires_in_days
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/report", summary="Reporte ejecutivo por pilares")
async def governance_report(request: Request):
    from src.platform.governance.board import executive_report
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await executive_report(ctx.organization_id)


class PolicyReviseIn(BaseModel):
    content: str = Field(min_length=10, max_length=5000)


class DecisionIn(BaseModel):
    decision_type: str = Field(pattern="^(deploy_approval|incident_review|policy_change|model_change)$")
    title: str = Field(min_length=3, max_length=200)
    rationale: str | None = Field(default=None, max_length=1000)
    target_id: str | None = None


class DecideIn(BaseModel):
    approve: bool = True


class CertificationIn(BaseModel):
    member_name: str = Field(min_length=1, max_length=150)
    certification: str = Field(max_length=40)
    expires_in_days: int = Field(default=365, ge=1, le=3650)

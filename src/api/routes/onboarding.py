# =============================================================================
# Tenant Onboarding Experience v2 — checklist, guías y wizard.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.infrastructure.postgres.relational_db import PostgresWorkspaceRepository
from src.platform.workspaces.service import choose_trial_start_mode

router = APIRouter(prefix="/api/v1/onboarding", tags=["Onboarding"])


class StartModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(demo|blank)$")


@router.post("/start-mode", summary="Preparar el workspace vacío del trial")
async def trial_start_mode(body: StartModeRequest, request: Request):
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "workspaces:write")
    if ctx.user_id is None:
        raise HTTPException(400, "User session required")
    ws, _created = await choose_trial_start_mode(
        PostgresWorkspaceRepository(),
        ctx.organization_id,
        ctx.user_id,
        body.mode,
    )
    return {
        "mode": body.mode,
        "workspace_id": str(ws.id),
        "kind": getattr(ws.kind, "value", str(ws.kind)),
        "needs_start_mode": False,
    }


@router.get("", summary="Estado del onboarding (checklist + guía)")
async def tenant_onboarding_state(request: Request):
    from src.platform.onboardingv2.onboarding import org_state
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await org_state(ctx.organization_id)


@router.get("/progress", summary="Progreso crudo del checklist")
async def tenant_onboarding_progress(request: Request):
    from src.platform.onboardingv2.onboarding import get_progress
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    return await get_progress(ctx.organization_id)


@router.post("/steps/{step}/complete", summary="Marcar paso completado")
async def tenant_onboarding_complete(step: str, request: Request):
    from src.platform.onboardingv2.onboarding import complete_step
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:write")
    try:
        return await complete_step(ctx.organization_id, step)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/guides", summary="Guía contextual del siguiente paso")
async def tenant_onboarding_guides(request: Request):
    from src.platform.onboardingv2.onboarding import GUIDES, org_state
    from src.platform.rbac.policy import require_permission

    ctx = require_permission(request, "billing:read")
    state = await org_state(ctx.organization_id)
    return {
        "guide": state["guide"],
        "next_step": state["next_step"],
        "all_guides": GUIDES,
    }

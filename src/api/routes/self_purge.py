# =============================================================================
# Self Purge API — borrado total self-service (allowlist por env)
# =============================================================================
# Solo para emails en RAG_SELF_PURGE_EMAILS. Borra toda la data de la
# organización y conserva usuario/membresía/organización/suscripción.
# Exige org admin + confirmación tipada + step-up.
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger
from src.platform.rbac.policy import require_permission
from src.platform.self_purge.service import PurgeInProgressError, SelfPurgeService
from src.platform.workspaces.step_up import require_tenant_step_up

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/self-purge", tags=["SelfPurge"])


def _svc() -> SelfPurgeService:
    return SelfPurgeService()


def _not_allowed() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "error_code": "self_purge_not_allowed",
            "message": "Self purge is not available for this account",
        },
    )


def _admin_required() -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "error_code": "organization_admin_required",
            "message": "Organization admin role required for this operation",
        },
    )


async def _allowed_email(request: Request) -> tuple[TenantContext, str]:
    ctx = require_permission(request, "org:read")
    if ctx.impersonated_by is not None:
        raise _not_allowed()
    service = _svc()
    email = await service.resolve_email(ctx.user_id)
    if not service.allowed(email):
        raise _not_allowed()
    return ctx, (email or "")


@router.get("/status", summary="¿Este usuario puede ejecutar el borrado total?")
async def status(request: Request):
    ctx = require_permission(request, "org:read")
    service = _svc()
    email: str | None = None
    allowed = False
    if ctx.impersonated_by is None:
        email = await service.resolve_email(ctx.user_id)
        allowed = service.allowed(email)
    return {
        "enabled": bool(service.allowed_emails()),
        "allowed": allowed,
        "email": email if allowed else None,
    }


@router.get("/preview", summary="Impacto del borrado (conteos antes de ejecutar)")
async def preview(request: Request):
    ctx, _email = await _allowed_email(request)
    if not ctx.is_organization_admin():
        raise _admin_required()
    return await _svc().preview(ctx.organization_id)


class ExecuteIn(BaseModel):
    model_config = {"extra": "forbid"}

    confirmation: str = Field(min_length=3, max_length=320)


@router.post("/execute", summary="Borrar toda la data de la organización")
async def execute(body: ExecuteIn, request: Request):
    ctx, email = await _allowed_email(request)
    if not ctx.is_organization_admin():
        raise _admin_required()
    if body.confirmation.strip().lower() != email:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "confirmation_mismatch",
                "message": "Escribe tu email exacto para confirmar el borrado",
            },
        )
    await require_tenant_step_up(request)
    try:
        result = await _svc().execute(ctx)
    except PurgeInProgressError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "purge_in_progress", "message": str(exc)},
        ) from exc
    await _revoke_current_session(request)
    return result


async def _revoke_current_session(request: Request) -> None:
    """Cierra la sesión que ejecutó el reset; el usuario vuelve a entrar limpio."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return
    try:
        from src.platform.auth.session import revoke_session

        await revoke_session(header[7:])
    except Exception as exc:  # noqa: BLE001 - la sesión expira sola si Redis no está
        logger.warning("self purge session revoke failed", error=str(exc)[:160])

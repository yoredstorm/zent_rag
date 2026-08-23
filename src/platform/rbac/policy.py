# =============================================================================
# RBAC — Política de autorización centralizada
# =============================================================================
# Las rutas y servicios declaran el permiso que exigen; la política decide
# contra el TenantContext (identidad ya autenticada). Nunca se toma una
# decisión de autorización con datos del cliente (headers/body).
# =============================================================================
from __future__ import annotations

from fastapi import HTTPException, Request, status

from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


def get_ctx(request: Request) -> TenantContext:
    """TenantContext desde request.state (puesto por TenantMiddleware)."""
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "authentication_required",
                "message": "Authentication required (Authorization: Bearer <token>)",
            },
        )
    return ctx


def require_permission(request: Request, permission: str) -> TenantContext:
    """Exige un permiso del catálogo. 403 con error_code si falta."""
    from src.platform.auth.scopes import permission_satisfied

    ctx = get_ctx(request)
    if ctx.has_permission(permission) or permission_satisfied(ctx.permissions, permission):
        return ctx
    if ctx.is_platform_admin():
        # admin:* (tokens de plataforma) pasa toda policy de recursos
        return ctx
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "permission_denied",
            "message": f"Missing required permission: {permission}",
        },
    )


def require_organization_admin(request: Request) -> TenantContext:
    """Owner/admin de la organización (gestiona usuarios, keys, prompts)."""
    ctx = get_ctx(request)
    if ctx.is_organization_admin():
        return ctx
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "organization_admin_required",
            "message": "Organization admin role required for this operation",
        },
    )


def require_platform_admin(request: Request) -> TenantContext:
    """Admin de plataforma: SOLO scope admin:* (nunca sesiones portal)."""
    ctx = get_ctx(request)
    if ctx.is_platform_admin():
        return ctx
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "platform_admin_required",
            "message": "Platform admin scope (admin:*) required for this operation",
        },
    )

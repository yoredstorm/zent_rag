# =============================================================================
# Authorization Service — autorización centralizada (platform + tenant)
# =============================================================================
# Fin de los checks ad-hoc ("if role == admin"). Toda decisión pasa por
# authorize() / require_permission() / require_platform_permission() contra
# la identidad autenticada (TenantContext). Nunca contra headers/body.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request, status

from src.core.domain.entities import TenantContext


class AuthorizationError(Exception):
    """Permiso insuficiente (capa de servicio, no HTTP)."""

    def __init__(self, permission: str, tenant_id: UUID | None = None) -> None:
        self.permission = permission
        self.tenant_id = tenant_id
        super().__init__(f"Missing required permission: {permission}")


def authorize(
    identity: TenantContext,
    permission: str,
    tenant_id: UUID | None = None,
) -> TenantContext:
    """Chequeo de autorización reutilizable por rutas Y servicios.

    - `permission` vacío: solo identidad (no se autoriza nada con identidad
      anónima; un TenantContext es requisito del middleware).
    - `admin:*` en scopes (API key de plataforma/tenant) pasa todo.
    - Si `tenant_id` se provee y difiere del tenant autenticado → denegado
      (defensa anti cross-tenant en servicios).
    """
    if tenant_id is not None and identity.tenant_id is not None:
        if identity.tenant_id != tenant_id:
            raise AuthorizationError(permission, tenant_id)

    if identity.has_permission(permission):
        return identity
    if "admin:*" in identity.scopes:
        return identity
    raise AuthorizationError(permission, tenant_id)


def get_ctx(request: Request) -> TenantContext:
    from src.platform.rbac.policy import get_ctx as _policy_ctx

    return _policy_ctx(request)


def require_platform_permission(request: Request, permission: str) -> TenantContext:
    """Permiso granular de plataforma (Control Center).

    Solo sesiones `platform_session` (o API key con `admin:*`). super_admin y
    platform_admin llevan `admin:*` en scopes → pasan todo. El resto debe
    tener el permiso exacto.
    """
    from src.platform.auth.scopes import permission_satisfied

    ctx = get_ctx(request)
    if ctx.auth_type == "platform_session" or "admin:*" in ctx.scopes:
        if ctx.has_permission(permission) or "admin:*" in ctx.scopes:
            return ctx
        if permission_satisfied(ctx.permissions, permission):
            return ctx
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "platform_permission_denied",
                "message": f"Missing required platform permission: {permission}",
            },
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error_code": "platform_admin_required",
            "message": "Platform admin session required for this operation",
        },
    )


def require_platform_permission_raw(
    ctx: TenantContext, permission: str
) -> TenantContext:
    """Versión sin Request (para servicios/workers)."""
    if ctx.auth_type != "platform_session" and "admin:*" not in ctx.scopes:
        raise AuthorizationError(permission)
    if "admin:*" in ctx.scopes or ctx.has_permission(permission):
        return ctx
    raise AuthorizationError(permission)

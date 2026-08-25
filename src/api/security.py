# =============================================================================
# API Security Helpers — Centralized identity resolution (organization / role / admin)
# =============================================================================
# Principios:
# 1. La identidad SIEMPRE proviene del TenantContext autenticado
#    (establecido por TenantMiddleware desde el Bearer validado).
# 2. X-Organization-Id / X-User-Id son opcionales y NUNCA elevan privilegios:
#    si difieren del contexto autenticado -> 403.
# 3. El rol efectivo se deriva server-side. El cliente solo puede
#    degradar (admin -> customer), jamás elevar (customer -> admin).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from starlette import status

from src.core.domain.entities import AuthenticatedContext, TenantContext
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_ROLE_VALUES = {"admin", "customer"}


def get_auth_context(request: Request) -> AuthenticatedContext:
    """Retorna el TenantContext autenticado establecido por TenantMiddleware."""
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


get_authenticated_context = get_auth_context


ORG_HEADER_DESCRIPTION = (
    "Opcional. Si se envía y no coincide con la organización del Bearer, la API responde 403."
)
USER_HEADER_DESCRIPTION = (
    "Opcional. Si se envía y no coincide con el usuario autenticado del Bearer, la API responde 403."
)
ROLE_HEADER_DESCRIPTION = (
    "Ignorado para autorización. Solo puede degradar el rol RAG (admin→customer); nunca eleva."
)


def get_billing_context(request: Request):
    """Contexto de billing (plan/quota) — también resuelto por TenantMiddleware."""
    ctx = getattr(request.state, "billing_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "authentication_required",
                "message": "Authentication required (Authorization: Bearer <token>)",
            },
        )
    return ctx


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} must be a valid UUID",
        )


def resolve_organization(
    request: Request,
    x_organization_id: str = "",
    *,
    require_auth: bool = True,
) -> UUID:
    """Resuelve la organización: el Bearer autenticado gana; header mismatch -> 403.

    - Con contexto autenticado: devuelve ctx.tenant_id. Si X-Organization-Id viene
      y difiere, 403 (evita cross-organization silencioso).
    - Sin contexto autenticado (rutas públicas que necesiten organización):
      usa X-Organization-Id (o el valor residual de request.state.organization_id).
    """
    ctx = getattr(request.state, "tenant_context", None)
    if ctx is not None:
        if x_organization_id:
            header_oid = _parse_uuid(x_organization_id, "X-Organization-Id")
            if header_oid != ctx.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "organization_mismatch",
                        "message": "X-Organization-Id does not match the authenticated organization",
                    },
                )
        return ctx.tenant_id

    if require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Authorization: Bearer <token>)",
        )

    organization_id_str = x_organization_id or getattr(request.state, "organization_id", "")
    if not organization_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Organization-Id header is required",
        )
    return _parse_uuid(str(organization_id_str), "X-Organization-Id")


async def resolve_user_id(request: Request, x_user_id: str) -> UUID:
    """Resuelve el usuario: la sesión autenticada gana; header mismatch -> 403.

    Para API keys (sin usuario de sesión), el TenantMiddleware ya resolvió el
    usuario por defecto de la organización; X-User-Id solo actúa como
    atribución dentro de la organización si coincide.
    """
    ctx = get_auth_context(request)

    if ctx.user_id is not None:
        if x_user_id:
            header_uid = _parse_uuid(x_user_id, "X-User-Id")
            if header_uid != ctx.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "error_code": "user_mismatch",
                        "message": "X-User-Id does not match the authenticated user",
                    },
                )
        return ctx.user_id

    if x_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "user_mismatch",
                "message": "X-User-Id is not an identity authority and does not match the authenticated user",
            },
        )

    from src.infrastructure.postgres.relational_db import PostgresUserRepository

    user_repo = PostgresUserRepository()
    try:
        default_user = await user_repo.get_by_external_id(ctx.tenant_id, "default-admin")
        if default_user is None:
            default_user = await user_repo.get_any_user(ctx.tenant_id)
    except Exception as exc:
        logger.error("Failed to resolve default user", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve user for this organization",
        )
    if default_user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No users found for this organization. Create a user first.",
        )
    return default_user.id


async def resolve_server_role(request: Request) -> str:
    """Rol server-side del principal autenticado (para el pipeline RAG).

    - Sesión portal: roles del TenantContext (owner/admin -> 'admin',
      resto -> 'customer').
    - API key: 'admin' si tiene scope admin:*, 'customer' si tiene scope
      rag:customer; por defecto 'admin' (compat con tokens legacy).
    """
    ctx = get_auth_context(request)

    if ctx.auth_type == "portal_session":
        return "admin" if ctx.is_organization_admin() else "customer"

    if "admin:*" in ctx.scopes:
        return "admin"
    if "rag:customer" in ctx.scopes:
        return "customer"
    return "admin"


async def resolve_effective_role(
    request: Request,
    client_role: str | None,
) -> str:
    """Rol efectivo: server role manda; el cliente solo puede degradar.

    client_role=None -> server role.
    client_role='customer' con server role 'admin' -> 'customer' (degrade, ok).
    client_role='admin' con server role 'customer' -> 'customer' (no eleva).
    """
    server_role = await resolve_server_role(request)
    requested = client_role if client_role in _ROLE_VALUES else None

    if server_role == "admin":
        return requested if requested else "admin"
    return "customer"


def require_organization_admin(request: Request) -> TenantContext:
    """Exige rol admin de la organización (operaciones administrativas)."""
    from src.platform.rbac.policy import require_organization_admin as _require

    return _require(request)


def require_platform_admin(request: Request) -> TenantContext:
    """Exige rol admin de plataforma (operaciones cross-organization)."""
    from src.platform.rbac.policy import require_platform_admin as _require

    return _require(request)


def require_scope(request: Request, scope: str) -> TenantContext:
    """Exige un scope específico en el token/sesión autenticada."""
    from src.platform.auth.scopes import has_scope

    ctx = get_auth_context(request)
    if not has_scope(ctx.scopes, scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )
    return ctx

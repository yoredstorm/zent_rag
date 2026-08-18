# =============================================================================
# API Security Helpers — Centralized identity resolution (tenant / role / admin)
# =============================================================================
# Principios:
# 1. La identidad SIEMPRE proviene del contexto autenticado (BillingMiddleware).
# 2. X-Tenant-Id / X-User-Id son opcionales y NUNCA elevan privilegios:
#    si difieren del contexto autenticado -> 403.
# 3. El rol efectivo se deriva server-side. El cliente solo puede
#    degradar (admin -> customer), jamás elevar (customer -> admin).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from starlette import status

from src.domain.entities import BillingContext
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_ROLE_VALUES = {"admin", "customer"}


def get_auth_context(request: Request) -> BillingContext | None:
    """Retorna el contexto autenticado establecido por BillingMiddleware."""
    ctx = getattr(request.state, "billing_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Authorization: Bearer <token>)",
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


def resolve_tenant(
    request: Request,
    x_tenant_id: str = "",
    *,
    require_auth: bool = True,
) -> UUID:
    """Resuelve el tenant: el Bearer autenticado gana; header mismatch -> 403.

    - Con contexto autenticado: devuelve ctx.tenant_id. Si X-Tenant-Id viene
      y difiere, 403 (evita cross-tenant silencioso).
    - Sin contexto autenticado (rutas públicas que necesiten tenant):
      usa X-Tenant-Id (o el valor residual de request.state.tenant_id).
    """
    ctx = getattr(request.state, "billing_context", None)
    if ctx is not None:
        if x_tenant_id:
            header_tid = _parse_uuid(x_tenant_id, "X-Tenant-Id")
            if header_tid != ctx.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="X-Tenant-Id does not match the authenticated tenant",
                )
        return ctx.tenant_id

    if require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Authorization: Bearer <token>)",
        )

    tenant_id_str = x_tenant_id or getattr(request.state, "tenant_id", "")
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Id header is required",
        )
    return _parse_uuid(str(tenant_id_str), "X-Tenant-Id")


async def resolve_user_id(request: Request, x_user_id: str) -> UUID:
    """Resuelve el usuario: la sesión autenticada gana; header mismatch -> 403.

    Para API tokens (sin usuario de sesión), acepta X-User-Id como
    atribución dentro del tenant, con fallback al usuario por defecto.
    """
    ctx = get_auth_context(request)

    if ctx.user_id is not None:
        if x_user_id:
            header_uid = _parse_uuid(x_user_id, "X-User-Id")
            if header_uid != ctx.user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="X-User-Id does not match the authenticated user",
                )
        return ctx.user_id

    if x_user_id:
        return _parse_uuid(x_user_id, "X-User-Id")

    from src.infrastructure.relational_db import PostgresUserRepository

    user_repo = PostgresUserRepository()
    try:
        default_user = await user_repo.get_by_external_id(ctx.tenant_id, "default-admin")
        if default_user is None:
            default_user = await user_repo.get_any_user(ctx.tenant_id)
    except Exception as exc:
        logger.error("Failed to resolve default user", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve user for this tenant",
        )
    if default_user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No users found for this tenant. Create a user first.",
        )
    return default_user.id


async def resolve_server_role(request: Request) -> str:
    """Rol server-side del principal autenticado.

    - Sesión portal: users.role de la BD (admin -> 'admin', resto -> 'customer').
    - API token: 'admin' si tiene scope admin:*, 'customer' si tiene scope
      rag:customer; por defecto el token del dueño del tenant es 'admin'.
    """
    ctx = get_auth_context(request)

    if ctx.auth_type == "portal_session" and ctx.user_id is not None:
        from src.infrastructure.relational_db import PostgresUserRepository

        user_repo = PostgresUserRepository()
        try:
            user = await user_repo.get_by_id(ctx.user_id, ctx.tenant_id)
        except Exception:
            user = None
        if user is not None:
            return "admin" if (user.role or "").lower() == "admin" else "customer"

    scopes = ctx.scopes or []
    if "admin:*" in scopes:
        return "admin"
    if "rag:customer" in scopes:
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


def is_tenant_admin(ctx: BillingContext) -> bool:
    """Admin del tenant: sesión portal del dueño o token con scope admin:*."""
    return ctx.auth_type == "portal_session" or "admin:*" in (ctx.scopes or [])


def is_platform_admin(ctx: BillingContext) -> bool:
    """Admin de plataforma: solo tokens con scope admin:* (nunca sesión portal)."""
    return "admin:*" in (ctx.scopes or [])


def require_tenant_admin(request: Request) -> BillingContext:
    """Exige rol admin del tenant (operaciones administrativas del tenant)."""
    ctx = get_auth_context(request)
    if not is_tenant_admin(ctx):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin role required for this operation",
        )
    return ctx


def require_platform_admin(request: Request) -> BillingContext:
    """Exige rol admin de plataforma (operaciones cross-tenant de la plataforma)."""
    ctx = get_auth_context(request)
    if not is_platform_admin(ctx):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin scope (admin:*) required for this operation",
        )
    return ctx


def require_scope(request: Request, scope: str) -> BillingContext:
    """Exige un scope específico en el token/sesión autenticada."""
    ctx = get_auth_context(request)
    scopes = ctx.scopes or []
    if scope not in scopes and "admin:*" not in scopes and "portal" not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )
    return ctx

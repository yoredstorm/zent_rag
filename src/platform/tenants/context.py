# =============================================================================
# Tenant Context — Propagación de identidad autenticada entre capas
# =============================================================================
# El TenantContext se deriva EXCLUSIVAMENTE de la identidad autenticada
# (API key hasheada o sesión portal AES-GCM). Nunca se construye desde
# headers (X-Organization-Id / X-User-Id / X-User-Role) ni desde el body
# de la request.
#
# Propagación:
# - HTTP: TenantMiddleware lo deposita en request.state.tenant_context y lo
#   publica en este ContextVar (el handler y toda la pila de llamadas lo leen).
# - Background (worker de ingestion): el job de Redis lleva organization_id;
#   el worker restaura el ContextVar con un TenantContext "system" antes de
#   procesar (nunca con roles/permisos elevados).
# =============================================================================
from __future__ import annotations

import contextvars
from uuid import UUID

from src.core.domain.entities import AuthenticatedContext, TenantContext

_current_tenant_context: contextvars.ContextVar[TenantContext | None] = (
    contextvars.ContextVar("zent_tenant_context", default=None)
)


def set_tenant_context(ctx: TenantContext) -> None:
    """Publica el TenantContext en el ContextVar del hilo/task actual."""
    _current_tenant_context.set(ctx)


def get_tenant_context() -> TenantContext | None:
    """Lee el TenantContext del ContextVar (None si no hay identidad)."""
    return _current_tenant_context.get()


def get_authenticated_context() -> AuthenticatedContext | None:
    """Alias del spec: misma identidad que get_tenant_context()."""
    return get_tenant_context()


def bind_organization_id(organization_id: UUID) -> UUID:
    """Si hay contexto autenticado, el organization_id DEBE coincidir con él."""
    ctx = get_tenant_context()
    if ctx is None:
        return organization_id
    if organization_id != ctx.tenant_id:
        raise ValueError(
            "organization_id does not match the authenticated tenant"
        )
    return ctx.tenant_id


def clear_tenant_context() -> None:
    _current_tenant_context.set(None)


def system_context(organization_id: UUID) -> TenantContext:
    """Contexto para jobs de background: solo identifica la organización,
    sin roles/permisos (nunca se amplía el privilegio de un job)."""
    return TenantContext(
        tenant_id=organization_id,
        user_id=None,
        roles=frozenset(),
        permissions=frozenset(),
        scopes=frozenset(),
        auth_type="system",
    )

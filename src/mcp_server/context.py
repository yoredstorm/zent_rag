# =============================================================================
# MCP Server — Resolución de identidad (NUNCA desde arguments del cliente)
# =============================================================================
# La identidad proviene EXCLUSIVAMENTE del TenantContext que TenantMiddleware
# publicó en el ContextVar tras validar el Bearer (API key o sesión portal).
# Los arguments de la tool (organization_id, user_id, role…) NUNCA definen
# identidad; el rol solo puede DEGRADARSE, jamás elevarse.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.core.domain.entities import TenantContext
from src.infrastructure.observability.logging_config import get_logger
from src.mcp_server.errors import McpAuthError
from src.platform.tenants.context import get_tenant_context

logger = get_logger(__name__)

_ROLE_VALUES = ("admin", "customer")

# Header opcional para que el cliente MCP se identifique ("name/version").
CLIENT_HEADER = "x-zent-mcp-client"


def resolve_tenant_context() -> TenantContext:
    """TenantContext autenticado (puesto por TenantMiddleware en cada request)."""
    ctx = get_tenant_context()
    if ctx is None:
        raise McpAuthError()
    return ctx


def resolve_server_role(ctx: TenantContext) -> str:
    """Rol server-side del principal autenticado (espejo de api/security.py)."""
    if ctx.auth_type == "portal_session":
        return "admin" if ctx.is_organization_admin() else "customer"
    if "admin:*" in ctx.scopes:
        return "admin"
    if "rag:customer" in ctx.scopes:
        return "customer"
    return "admin"


def resolve_effective_role(ctx: TenantContext, client_role: str | None) -> str:
    """Server role manda; el cliente solo puede degradar (admin -> customer)."""
    server_role = resolve_server_role(ctx)
    requested = client_role if client_role in _ROLE_VALUES else None
    if server_role == "admin":
        return requested if requested else "admin"
    return "customer"


@dataclass(kw_only=True)
class McpCallIdentity:
    """Identidad + metadata de un tool call MCP (para policy y auditoría)."""

    tenant: TenantContext
    tool: str
    role: str
    call_id: str
    mcp_client: str = "unknown"


def client_identity_from_headers(headers: dict[str, str] | None) -> str:
    """Identifica al cliente MCP: header dedicado o User-Agent del protocolo.

    En transporte stateless el clientInfo del handshake initialize no está
    disponible en el momento del tools/call; los clientes estándar envían un
    User-Agent descriptivo en cada request (ej: 'claude-desktop/1.2.3').
    """
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    dedicated = lowered.get(CLIENT_HEADER)
    if dedicated:
        return dedicated[:120]
    user_agent = lowered.get("user-agent")
    if user_agent:
        return user_agent[:120]
    return "unknown"


def new_call_id() -> str:
    """ID idempotente del tool call (usage events UNIQUE(request_id, event_type))."""
    return str(uuid4())

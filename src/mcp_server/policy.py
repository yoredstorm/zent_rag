# =============================================================================
# MCP Server — Política de tools (RBAC + config por tenant + rate limits)
# =============================================================================
# Ninguna tool MCP se ejecuta sin pasar por aquí. El MCP server NO es un
# camino alternativo: usa los MISMOS permisos RBAC, la MISMA cuota de plan
# (TenantMiddleware) y añade un rate limit por tool namespaced por tenant.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.core.config import get_settings
from src.core.domain.entities import TenantContext
from src.core.ports import CacheProvider
from src.infrastructure.observability.logging_config import get_logger
from src.mcp_server.errors import McpPolicyError
from src.platform.auth.scopes import permission_satisfied

logger = get_logger(__name__)

# Mapeo tool -> permiso RBAC (mismo catálogo que REST/agents).
TOOL_PERMISSIONS: dict[str, str] = {
    "search_knowledge": "rag:read",
    "query_database": "rag:read",
    "get_document": "rag:read",
    "execute_agent": "agents:execute",
    "get_usage": "usage:read",
}

# Requests/minuto por defecto por tool (override por organización).
DEFAULT_TOOL_RPM: dict[str, int] = {
    "search_knowledge": 60,
    "query_database": 20,
    "get_document": 60,
    "execute_agent": 10,
    "get_usage": 30,
}

_RATE_WINDOW_SECONDS = 60


class McpRateLimiter:
    """Ventana fija por tool + tenant en Redis (fail-open, como ToolRateLimiter)."""

    def __init__(self, cache: CacheProvider | None) -> None:
        self._cache = cache

    async def check(self, tenant_id: UUID, tool: str, rpm: int) -> bool:
        if self._cache is None:
            return True
        key = f"mcp:tool:{tenant_id.hex}:{tool}"
        try:
            count = await self._cache.incr(key, ttl_seconds=_RATE_WINDOW_SECONDS)
            return count <= rpm
        except Exception as exc:
            # Fail-open consistente con el resto de la plataforma; el rate
            # limit global por organización (RateLimitMiddleware) sigue activo.
            logger.warning("MCP tool rate limit failed open", tool=tool, error=str(exc))
            return True


class McpPolicy:
    """Autorización de tools MCP: permiso -> config del tenant -> rate limit."""

    def __init__(self, rate_limiter: McpRateLimiter) -> None:
        self._rate_limiter = rate_limiter

    @staticmethod
    def _required_permission(tool: str) -> str:
        return TOOL_PERMISSIONS.get(tool, "")

    @staticmethod
    def _org_mcp_config(org_config: dict | None) -> dict:
        return (org_config or {}).get("mcp") or {}

    def check_permission(self, ctx: TenantContext, tool: str) -> None:
        required = self._required_permission(tool)
        if not required:
            raise McpPolicyError(f"Tool not allowed over MCP: {tool}", "tool_not_allowed")
        if ctx.is_platform_admin():
            return
        if permission_satisfied(ctx.permissions, required) or ctx.has_permission(required):
            return
        raise McpPolicyError(
            f"Missing required permission for tool '{tool}': {required}",
            "permission_denied",
        )

    def check_org_policy(
        self,
        ctx: TenantContext,
        tool: str,
        role: str,
        org_config: dict | None,
    ) -> int:
        """Aplica config_json['mcp'] del tenant. Retorna el rpm efectivo."""
        cfg = self._org_mcp_config(org_config)
        settings = get_settings()
        if cfg.get("enabled") is False:
            raise McpPolicyError(
                "MCP is disabled for this organization", "mcp_disabled"
            )
        tool_cfg = (cfg.get("tools") or {}).get(tool) or {}
        if tool_cfg.get("enabled") is False:
            raise McpPolicyError(
                f"Tool '{tool}' is disabled for this organization",
                "tool_disabled",
            )
        min_role = tool_cfg.get("min_role")
        if min_role in ("admin", "customer"):
            if role != "admin" and min_role == "admin":
                raise McpPolicyError(
                    f"Tool '{tool}' requires admin role", "role_required"
                )
        rpm = int(tool_cfg.get("rpm") or DEFAULT_TOOL_RPM.get(tool) or settings.RAG_MCP_DEFAULT_RPM)
        return max(1, rpm)

    async def authorize(
        self,
        ctx: TenantContext,
        tool: str,
        role: str,
        org_config: dict | None,
    ) -> None:
        """Gate completo de una tool call. Lanza McpPolicyError si deniega."""
        self.check_permission(ctx, tool)
        rpm = self.check_org_policy(ctx, tool, role, org_config)
        allowed = await self._rate_limiter.check(ctx.tenant_id, tool, rpm)
        if not allowed:
            raise McpPolicyError(
                f"Rate limit exceeded for tool '{tool}' ({rpm} req/min)",
                "rate_limited",
            )

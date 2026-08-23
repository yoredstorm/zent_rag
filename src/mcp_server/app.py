# =============================================================================
# MCP Server — app factory + transporte Streamable HTTP (stateless)
# =============================================================================
# stateless_http=True: cada request MCP es independiente y lleva su propio
# Bearer token (validado por TenantMiddleware de la API). No hay sesiones
# server-side: identidad por request, cero estado compartido entre clients.
# streamable_http_path='/' porque la app se monta bajo /mcp en la API.
# =============================================================================
from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from src.core.config import get_settings
from src.mcp_server.tools import register_tools

SERVER_NAME = "zent"
SERVER_VERSION = "1.0.0"


def build_mcp_http_app(deps=None):
    """Construye la sub-app ASGI del MCP server (montada en /mcp)."""
    server = MCPServer(
        name=SERVER_NAME,
        title="Zent MCP Server",
        description=(
            "Zent capabilities over Model Context Protocol: search_knowledge, "
            "query_database, get_document, execute_agent, get_usage."
        ),
        version=SERVER_VERSION,
        instructions=(
            "Every request must include 'Authorization: Bearer <api key>'. "
            "All tools are scoped to the authenticated organization and "
            "subject to RBAC, quotas and tool policies."
        ),
    )
    register_tools(server, deps=deps)

    settings = get_settings()
    hosts = [h.strip() for h in settings.RAG_MCP_ALLOWED_HOSTS.split(",") if h.strip()]
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=bool(hosts),
            allowed_hosts=hosts,
        ),
    )

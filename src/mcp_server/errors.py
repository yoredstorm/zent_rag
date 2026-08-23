# =============================================================================
# MCP Server — errores de dominio del protocolo
# =============================================================================
from __future__ import annotations


class McpAuthError(Exception):
    """Identidad ausente o inválida (el TenantMiddleware no autenticó)."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message)
        self.error_code = "authentication_required"


class McpPolicyError(Exception):
    """La política (RBAC / config del tenant / rate limit) deniega la tool."""

    def __init__(self, message: str, error_code: str = "permission_denied") -> None:
        super().__init__(message)
        self.error_code = error_code


class McpToolError(Exception):
    """Error de ejecución de una tool (se expone al cliente como isError)."""

    def __init__(self, message: str, error_code: str = "tool_error") -> None:
        super().__init__(message)
        self.error_code = error_code

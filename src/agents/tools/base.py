# =============================================================================
# Tool Framework — contrato base del Agent Runtime
# =============================================================================
# Un Tool es la ÚNICA vía por la que un agente interactúa con el mundo.
# El modelo NUNCA ejecuta funciones arbitrarias: solo tools registradas,
# dentro del allowlist del agente, con permiso RBAC, timeout y rate limit.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar
from uuid import UUID


@dataclass(kw_only=True, frozen=True)
class ToolContext:
    """Contexto de ejecución inyectado por el runtime. El modelo NO lo
    controla: tenant/user/role vienen de la request autenticada."""

    tenant_id: UUID
    user_id: UUID | None = None
    role: str = "admin"
    permissions: frozenset[str] = frozenset()
    conversation_id: UUID | None = None
    org_config: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class ToolResult:
    """Resultado de una ejecución de tool (observación para el LLM)."""

    output: str = ""
    error: str | None = None
    latency_ms: float = 0.0
    truncated: bool = False
    tokens: int = 0


class ToolError(Exception):
    """Base de errores de tools (controlados, auditados)."""


class ToolPermissionError(ToolError):
    """El tenant/rol no tiene permiso para esta tool."""


class ToolRateLimitedError(ToolError):
    """Rate limit excedido para esta tool."""


class ToolTimeoutError(ToolError):
    """La tool excedió su timeout."""


class ToolInputError(ToolError):
    """Los argumentos no cumplen el input_schema."""


class Tool(ABC):
    """Contrato de herramienta del Agent Runtime.

    Atributos de clase (declarativos):
      - name: identificador único (referenciado por agent.tools).
      - description: qué hace (va al prompt del LLM).
      - input_schema: JSON Schema de los argumentos (validado por runtime).
      - permission: código RBAC requerido ('' = solo allowlist del agente).
      - timeout_seconds: timeout duro por ejecución.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}
    permission: ClassVar[str] = ""
    timeout_seconds: ClassVar[float] = 10.0

    @abstractmethod
    async def execute(self, ctx: ToolContext, arguments: dict) -> ToolResult:
        """Ejecuta la tool con argumentos validados. Nunca lanza excepciones
        no controladas: errores esperados van en ToolResult.error."""

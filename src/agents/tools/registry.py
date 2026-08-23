# =============================================================================
# Tool Registry — registro, lookup y allowlist del Agent Runtime
# =============================================================================
from __future__ import annotations

import importlib

from src.agents.tools.base import Tool, ToolContext
from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_tools: dict[str, Tool] = {}


def register_tool(tool: Tool) -> None:
    """Registra una instancia de tool por su name."""
    if not tool.name:
        raise ValueError("Tool must define a non-empty name")
    if tool.name in _tools:
        logger.warning("Tool re-registered, replacing", tool=tool.name)
    _tools[tool.name] = tool


def get_tool(name: str) -> Tool | None:
    return _tools.get(name)


def list_tools() -> dict[str, Tool]:
    return dict(_tools)


def load_tool_modules(module_paths: list[str] | None = None) -> None:
    """Importa módulos verticales que registran tools (patrón heuristics)."""
    paths = module_paths
    if paths is None:
        paths = [
            p.strip()
            for p in get_settings().RAG_AGENT_TOOL_MODULES.split(",")
            if p.strip()
        ]
    for path in paths:
        try:
            module = importlib.import_module(path)
            register = getattr(module, "register", None)
            if callable(register):
                register()
            logger.info("Loaded agent tool module", module=path)
        except Exception as exc:
            logger.warning(
                "Failed to load agent tool module",
                module=path,
                error=str(exc),
            )


def _has_permission(ctx: ToolContext, permission: str) -> bool:
    if not permission:
        return True
    return "*" in ctx.permissions or permission in ctx.permissions


def tool_allowed(tool: Tool, agent_tools: list[str], ctx: ToolContext) -> bool:
    """Allowlist del agente + permiso RBAC del tenant. Doble gate."""
    if tool.name not in agent_tools:
        return False
    return _has_permission(ctx, tool.permission)


def resolve_allowed_tools(
    agent_tools: list[str],
    ctx: ToolContext,
) -> list[Tool]:
    """Tools del agente disponibles para este contexto (registradas + RBAC)."""
    resolved: list[Tool] = []
    for name in agent_tools:
        tool = get_tool(name)
        if tool is not None and tool_allowed(tool, agent_tools, ctx):
            resolved.append(tool)
    return resolved

# Re-export — implementation lives in infrastructure (no upward import).
from src.infrastructure.llm.router import (
    ROUTE_ALIASES,
    ResolvedRoute,
    generate_routed,
    list_route_catalog,
    resolve_route,
)

__all__ = [
    "ROUTE_ALIASES",
    "ResolvedRoute",
    "generate_routed",
    "list_route_catalog",
    "resolve_route",
]

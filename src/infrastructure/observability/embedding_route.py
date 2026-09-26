# =============================================================================
# Embedding route — qué proveedor sirvió el último embedding del task actual
# =============================================================================
# El proveedor de embeddings (LiteLLM) publica acá la ruta aplicada: primario
# (Novita) o respaldo (DeepInfra). El orquestador la lee para "Ver flujo".
#
# ContextVar, no atributo de instancia: cada request/task tiene la suya y la
# ingesta concurrente no la pisa. Nunca contiene secretos: modelo, proveedor y
# host, nada más.
# =============================================================================
from __future__ import annotations

from contextvars import ContextVar

_EMBED_ROUTE: ContextVar[dict | None] = ContextVar("embedding_route", default=None)
_FALLBACK_USED: ContextVar[bool] = ContextVar("embedding_fallback_used", default=False)


def set_embedding_route(route: dict) -> None:
    """Publica la ruta aplicada por el embedding recién resuelto."""
    _EMBED_ROUTE.set(dict(route))
    if route.get("fallback"):
        _FALLBACK_USED.set(True)


def last_embedding_route() -> dict | None:
    """Copia de la ruta del último embedding del task actual (None si no hubo)."""
    route = _EMBED_ROUTE.get()
    return dict(route) if route else None


def embedding_fallback_used() -> bool:
    """True si algún embedding del task actual usó el respaldo."""
    return _FALLBACK_USED.get()


__all__ = [
    "embedding_fallback_used",
    "last_embedding_route",
    "set_embedding_route",
]

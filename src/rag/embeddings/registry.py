# =============================================================================
# Embedding Capability Registry — lo que el modelo REALMENTE soporta
# =============================================================================
# Nunca asumir que un modelo soporta late chunking. La capacidad se resuelve:
#   1. override de configuración (RAG_EMBEDDING_LATE_CHUNKING_MODELS);
#   2. mapa builtin conservador (solo modelos cuyo API lo expone de verdad);
#   3. default: sin late chunking.
#
# Además de la capacidad, el provider concreto debe exponer el método real
# (`embed_late_chunking`); si no, el engine usa contextual embedding.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

#: Modelos cuyo API público expone late chunking por request (conservador).
_BUILTIN_LATE_CHUNKING: frozenset[str] = frozenset(
    {
        "jina-embeddings-v3",
        "jina-embeddings-v4",
        "voyage-context-3",
    }
)


@dataclass(frozen=True, kw_only=True)
class EmbeddingCapability:
    model_name: str
    supports_late_chunking: bool = False
    max_input_tokens: int = 8192
    dimensions: int = 0
    source: str = "default"

    def to_public_dict(self) -> dict:
        return {
            "model": self.model_name,
            "supports_late_chunking": self.supports_late_chunking,
            "max_input_tokens": self.max_input_tokens,
            "dimensions": self.dimensions,
            "source": self.source,
        }


def _normalize(model: str) -> str:
    value = (model or "").strip().lower()
    if "/" in value:  # litellm usa prefijo de proveedor: "jina_ai/jina-embeddings-v3"
        value = value.split("/", 1)[1]
    return value


def resolve_embedding_capability(
    model: str,
    *,
    late_chunking_models: set[str] | None = None,
    dimensions: int = 0,
    max_input_tokens: int = 8192,
) -> EmbeddingCapability:
    """Capacidad real del embedding: config gana, luego builtin, luego default."""
    normalized = _normalize(model) or "unknown"
    configured = {_normalize(item) for item in (late_chunking_models or set())}
    if normalized in configured:
        return EmbeddingCapability(
            model_name=model or normalized,
            supports_late_chunking=True,
            max_input_tokens=max_input_tokens,
            dimensions=dimensions,
            source="config",
        )
    if normalized in _BUILTIN_LATE_CHUNKING:
        return EmbeddingCapability(
            model_name=model or normalized,
            supports_late_chunking=True,
            max_input_tokens=max_input_tokens,
            dimensions=dimensions,
            source="builtin",
        )
    return EmbeddingCapability(
        model_name=model or normalized,
        supports_late_chunking=False,
        max_input_tokens=max_input_tokens,
        dimensions=dimensions,
        source="default",
    )


__all__ = ["EmbeddingCapability", "resolve_embedding_capability"]

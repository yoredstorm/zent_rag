# =============================================================================
# Reranker — Abstracción y registry
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.entities import RetrievalChunk


class Reranker(ABC):
    """Re-score post-retrieval. Implementaciones: llm, cross_encoder, none."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        chunks: list[RetrievalChunk],
        top_n: int = 20,
        organization_id: str = "",
    ) -> list[RetrievalChunk]:
        """Devuelve chunks reordenados por relevancia (máximo top_n)."""


class NoopReranker(Reranker):
    """Passthrough: conserva el orden del retrieval sin costo."""

    async def rerank(
        self,
        query: str,
        chunks: list[RetrievalChunk],
        top_n: int = 20,
        organization_id: str = "",
    ) -> list[RetrievalChunk]:
        return chunks[:top_n]


_RERANKERS: dict[str, type[Reranker]] = {}


def register_reranker(name: str, cls: type[Reranker]) -> None:
    _RERANKERS[name] = cls


def get_reranker(name: str | None, **kwargs) -> Reranker:
    """Devuelve instancia por nombre registrado; desconocido o None = Noop."""
    if not name:
        return NoopReranker()
    cls = _RERANKERS.get(name)
    if cls is None:
        return NoopReranker()
    return cls(**kwargs)

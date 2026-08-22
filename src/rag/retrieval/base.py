# =============================================================================
# Retriever — Abstracción del motor de retrieval
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.entities import RetrievalContext
from src.rag.retrieval.models import RetrievalQuery


class Retriever(ABC):
    """Abstracción del pipeline de retrieval completo.

    Implementaciones:
      - VectorRetriever: búsqueda semántica pura.
      - LexicalRetriever: búsqueda lexical pura (BM25).
      - HybridRetriever: fusión de ambas patas + rerank + threshold + budget.

    El negocio (orchestrator) depende SOLO de esta interfaz; nunca de
    adaptadores concretos.
    """

    @abstractmethod
    async def retrieve(self, query: RetrievalQuery) -> RetrievalContext: ...

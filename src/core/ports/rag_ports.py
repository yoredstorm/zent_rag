# =============================================================================
# Ports RAG — Capacidades genéricas (vector store, LLM, embeddings, caché)
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from uuid import UUID

from src.core.domain.entities import (
    LLMResponse,
    RAGQueryResult,
    RetrievalContext,
)


class VectorStore(ABC):
    """Puerto para búsqueda semántica (Qdrant) con aislamiento estricto.

    Contrato de seguridad: organization_id es OBLIGATORIO en toda operación.
    Toda búsqueda debe filtrar por organization_id en el payload; si un
    adaptador omite el filtro, es una fuga cross-tenant.
    """

    @abstractmethod
    async def search(
        self,
        organization_id: UUID,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
        knowledge_base_id: UUID | None = None,
    ) -> RetrievalContext: ...

    @abstractmethod
    async def upsert(
        self,
        organization_id: UUID,
        document_id: UUID,
        embedding: list[float],
        content: str,
        metadata: dict[str, str] | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> None: ...

    @abstractmethod
    async def upsert_batch(
        self,
        organization_id: UUID,
        points: list[tuple[UUID, list[float], str, dict[str, str] | None]],
        knowledge_base_id: UUID | None = None,
    ) -> None: ...

    @abstractmethod
    async def delete_by_organization(self, organization_id: UUID) -> None: ...

    @abstractmethod
    async def delete_by_knowledge_base(
        self, organization_id: UUID, knowledge_base_id: UUID
    ) -> None: ...


class LLMProvider(ABC):
    """Puerto para invocación de LLMs (LiteLLM)."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        system_prompt: str | None = None,
    ) -> AsyncIterator[dict[str, object]]:
        """Genera una respuesta token a token.

        Yields:
            {"type": "delta", "text": str} por cada fragmento.
            {"type": "done", "content": str, "model": str, "usage": {...},
             "finish_reason": str, "latency_ms": float} al finalizar.
        """

    @abstractmethod
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]: ...


class EmbeddingProvider(ABC):
    """Puerto para generación de embeddings (LiteLLM o proveedor directo)."""

    @abstractmethod
    async def embed(self, text: str | list[str], model: str | None = None) -> list[float] | list[list[float]]: ...


class CacheProvider(ABC):
    """Puerto para caché (Redis)."""

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int = 300) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def append_to_list(
        self, key: str, value: str, ttl_seconds: int = 3600
    ) -> None:
        """Agrega un item al final de una lista con TTL."""
        ...

    @abstractmethod
    async def get_list(self, key: str) -> list[str]:
        """Obtiene todos los items de una lista."""
        ...

    @abstractmethod
    async def trim_list(self, key: str, max_items: int) -> None:
        """Recorta la lista a max_items más recientes."""
        ...

    @abstractmethod
    async def incr(self, key: str, ttl_seconds: int | None = None, by: int = 1) -> int:
        """Incrementa un contador atómicamente y devuelve el valor.

        Si la clave no existe, se crea con valor `by` y se le aplica
        `ttl_seconds` (solo en la creación).
        """
        ...


class RAGQueryStore(ABC):
    """Puerto para persistencia de resultados de consultas (auditoría)."""

    @abstractmethod
    async def save(self, result: RAGQueryResult) -> None: ...

    @abstractmethod
    async def get_by_id(self, query_id: UUID, organization_id: UUID) -> RAGQueryResult | None: ...

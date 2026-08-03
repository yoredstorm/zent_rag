# =============================================================================
# Qdrant Vector Store Adapter — Búsqueda Semántica Multi-Tenant
# =============================================================================
# Colección única compartida (rag_documents) con filtrado por tenant_id
# en payload. Escala a cientos/miles de tenants sin overhead por colección.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar
from uuid import UUID

import httpx
from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qdrant_models

from src.config import get_settings
from src.domain.entities import RetrievalChunk, RetrievalContext
from src.domain.ports import VectorStore
from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

_T = TypeVar("_T")

TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
)

RETRY_BACKOFFS = (1.0, 2.0, 4.0)

RAG_DOCUMENTS_COLLECTION = "rag_documents"


async def _retry_on_transient_error(
    action: Callable[..., Awaitable[_T]],
    /,
    *args: object,
    **kwargs: object,
) -> _T:
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_BACKOFFS):
        try:
            return await action(*args, **kwargs)
        except TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            logger.warning(
                "Qdrant retry attempt failed",
                attempt=attempt + 1,
                max_retries=len(RETRY_BACKOFFS),
                error=str(exc),
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]

# -----------------------------------------------------------------------------
# Cliente Singleton, per-event-loop
# -----------------------------------------------------------------------------
_qdrant_client: AsyncQdrantClient | None = None
_qdrant_loop_id: int | None = None


async def _get_client() -> AsyncQdrantClient:
    global _qdrant_client, _qdrant_loop_id
    import asyncio as _asyncio
    current_loop_id = id(_asyncio.get_running_loop())
    if _qdrant_client is None or _qdrant_loop_id != current_loop_id:
        if _qdrant_client is not None:
            try:
                await _qdrant_client.close()
            except Exception:
                pass
        settings = get_settings()
        raw_key = settings.QDRANT_API_KEY.get_secret_value() if settings.QDRANT_API_KEY else ""
        api_key = raw_key if raw_key else None
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=api_key,
            grpc_port=settings.QDRANT_GRPC_PORT,
            prefer_grpc=False,
            timeout=float(settings.QDRANT_TIMEOUT_SECONDS),
        )
        _qdrant_loop_id = current_loop_id
    return _qdrant_client


class QdrantVectorStore(VectorStore):
    """Implementación de VectorStore con colección única compartida."""

    async def _ensure_collection(self) -> None:
        client = await _get_client()
        settings = get_settings()
        if not await client.collection_exists(RAG_DOCUMENTS_COLLECTION):
            await client.create_collection(
                collection_name=RAG_DOCUMENTS_COLLECTION,
                vectors_config=qdrant_models.VectorParams(
                    size=settings.VECTOR_DIMENSION,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )
            logger.info(
                "Created shared vector collection",
                collection_name=RAG_DOCUMENTS_COLLECTION,
                vector_dimension=settings.VECTOR_DIMENSION,
            )

    async def search(
        self,
        tenant_id: UUID,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
    ) -> RetrievalContext:
        client = await _get_client()
        await self._ensure_collection()

        start = time.perf_counter()

        must_conditions = [
            qdrant_models.FieldCondition(
                key="tenant_id",
                match=qdrant_models.MatchValue(value=str(tenant_id)),
            )
        ]

        if role == "customer":
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="metadata.visibility",
                    match=qdrant_models.MatchValue(value="public"),
                )
            )

        if filters:
            must_conditions.extend([
                qdrant_models.FieldCondition(
                    key=key,
                    match=qdrant_models.MatchValue(value=value),
                )
                for key, value in filters.items()
            ])

        qdrant_filter = qdrant_models.Filter(must=must_conditions)

        results = await _retry_on_transient_error(
            client.query_points,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            query=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
            score_threshold=score_threshold,
        )

        latency_ms = (time.perf_counter() - start) * 1000

        chunks = [
            RetrievalChunk(
                document_id=UUID(point.id) if point.id else UUID(int=0),
                content=point.payload.get("content", "") if point.payload else "",
                score=point.score,
                metadata=point.payload.get("metadata", {}) if point.payload else {},
            )
            for point in results.points
        ]

        logger.info(
            "Vector search completed",
            tenant_id=str(tenant_id),
            results_count=len(chunks),
            query_latency_ms=round(latency_ms, 2),
            top_score=round(chunks[0].score, 4) if chunks else 0.0,
        )

        return RetrievalContext(
            chunks=chunks,
            query_embedding=query_embedding,
            retrieval_latency_ms=latency_ms,
        )

    async def upsert(
        self,
        tenant_id: UUID,
        document_id: UUID,
        embedding: list[float],
        content: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        client = await _get_client()
        await self._ensure_collection()

        await _retry_on_transient_error(
            client.upsert,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            points=[
                qdrant_models.PointStruct(
                    id=str(document_id),
                    vector=embedding,
                    payload={
                        "content": content,
                        "metadata": metadata or {},
                        "tenant_id": str(tenant_id),
                    },
                )
            ],
        )

    async def delete_by_tenant(self, tenant_id: UUID) -> None:
        """Elimina todos los vectores de un tenant por filtro de payload."""
        client = await _get_client()
        await self._ensure_collection()

        await _retry_on_transient_error(
            client.delete,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            points_selector=qdrant_models.FilterSelector(
                filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="tenant_id",
                            match=qdrant_models.MatchValue(value=str(tenant_id)),
                        )
                    ]
                )
            ),
        )
        logger.info("Deleted tenant vectors from shared collection", tenant_id=str(tenant_id))


async def close_qdrant_connection() -> None:
    """Cierra la conexión con Qdrant."""
    global _qdrant_client, _qdrant_loop_id
    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None
        _qdrant_loop_id = None

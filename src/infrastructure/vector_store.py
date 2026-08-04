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

try:
    import httpcore
except ImportError:  # pragma: no cover
    httpcore = None  # type: ignore[assignment]

_TRANSIENT_BASE: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.NetworkError,
    httpx.ReadError,
    httpx.WriteError,
    asyncio.TimeoutError,
    ConnectionError,
    OSError,
    TimeoutError,
)
if httpcore is not None:
    _TRANSIENT_BASE = _TRANSIENT_BASE + (
        httpcore.RemoteProtocolError,
        httpcore.ConnectError,
        httpcore.ReadTimeout,
        httpcore.WriteTimeout,
        httpcore.ConnectTimeout,
    )

TRANSIENT_EXCEPTIONS = _TRANSIENT_BASE

RETRY_BACKOFFS = (0.5, 1.0, 2.0, 4.0, 8.0)

RAG_DOCUMENTS_COLLECTION = "rag_documents"

# Limit concurrent upserts across tables (table_concurrency > 1 used to flood Qdrant).
_upsert_sem: asyncio.Semaphore | None = None
_collection_ready = False


def _upsert_semaphore() -> asyncio.Semaphore:
    global _upsert_sem
    if _upsert_sem is None:
        settings = get_settings()
        _upsert_sem = asyncio.Semaphore(max(1, settings.QDRANT_UPSERT_CONCURRENCY))
    return _upsert_sem


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, TRANSIENT_EXCEPTIONS):
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    needles = (
        "disconnected",
        "connection reset",
        "broken pipe",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "server disconnected",
        "connection closed",
    )
    return any(n in msg for n in needles)


def _exc_text(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__


async def _retry_on_transient_error(
    action: Callable[..., Awaitable[_T]],
    /,
    *args: object,
    reset_client: bool = False,
    **kwargs: object,
) -> _T:
    last_exc: Exception | None = None
    attempts = len(RETRY_BACKOFFS) + 1
    for attempt in range(attempts):
        try:
            return await action(*args, **kwargs)
        except Exception as exc:
            if not _is_transient(exc):
                raise
            last_exc = exc  # type: ignore[assignment]
            if attempt >= len(RETRY_BACKOFFS):
                break
            logger.warning(
                "Qdrant retry attempt failed",
                attempt=attempt + 1,
                max_retries=len(RETRY_BACKOFFS),
                error=_exc_text(exc),
            )
            if reset_client:
                await close_qdrant_connection()
            await asyncio.sleep(RETRY_BACKOFFS[attempt])
    raise last_exc  # type: ignore[misc]


# -----------------------------------------------------------------------------
# Cliente Singleton, per-event-loop
# -----------------------------------------------------------------------------
_qdrant_client: AsyncQdrantClient | None = None
_qdrant_loop_id: int | None = None


async def _get_client() -> AsyncQdrantClient:
    global _qdrant_client, _qdrant_loop_id, _collection_ready
    import asyncio as _asyncio

    current_loop_id = id(_asyncio.get_running_loop())
    if _qdrant_client is None or _qdrant_loop_id != current_loop_id:
        if _qdrant_client is not None:
            try:
                await _qdrant_client.close()
            except Exception:
                pass
        settings = get_settings()
        raw_key = settings.QDRANT_API_KEY
        api_key = raw_key.get_secret_value() if raw_key else None
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=api_key,
            grpc_port=settings.QDRANT_GRPC_PORT,
            prefer_grpc=False,
            timeout=float(settings.QDRANT_TIMEOUT_SECONDS),
            check_compatibility=False,
        )
        _qdrant_loop_id = current_loop_id
        _collection_ready = False
    return _qdrant_client


class QdrantVectorStore(VectorStore):
    """Implementación de VectorStore con colección única compartida."""

    async def _ensure_collection(self) -> None:
        global _collection_ready
        if _collection_ready:
            return
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
        _collection_ready = True

    async def search(
        self,
        tenant_id: UUID,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
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

        must_not_conditions = []
        if exclude_filters:
            must_not_conditions.extend([
                qdrant_models.FieldCondition(
                    key=key,
                    match=qdrant_models.MatchValue(value=value),
                )
                for key, value in exclude_filters.items()
            ])

        qdrant_filter = qdrant_models.Filter(
            must=must_conditions,
            must_not=must_not_conditions or None,
        )

        results = await _retry_on_transient_error(
            client.query_points,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            query=query_embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
            score_threshold=score_threshold,
            reset_client=True,
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
        await self.upsert_batch(
            tenant_id,
            [(document_id, embedding, content, metadata)],
        )

    async def upsert_batch(
        self,
        tenant_id: UUID,
        points: list[tuple[UUID, list[float], str, dict[str, str] | None]],
    ) -> None:
        if not points:
            return

        async with _upsert_semaphore():
            client = await _get_client()
            await self._ensure_collection()

            structs = [
                qdrant_models.PointStruct(
                    id=str(document_id),
                    vector=embedding,
                    payload={
                        "content": content,
                        "metadata": metadata or {},
                        "tenant_id": str(tenant_id),
                    },
                )
                for document_id, embedding, content, metadata in points
            ]

            async def _do_upsert() -> None:
                # Fresh client each retry after reset_client=True
                c = await _get_client()
                await c.upsert(
                    collection_name=RAG_DOCUMENTS_COLLECTION,
                    points=structs,
                    wait=True,
                )

            await _retry_on_transient_error(_do_upsert, reset_client=True)

    async def delete_by_tenant(self, tenant_id: UUID) -> None:
        """Elimina todos los vectores de un tenant por filtro de payload."""
        async with _upsert_semaphore():
            client = await _get_client()
            await self._ensure_collection()

            async def _do_delete() -> None:
                c = await _get_client()
                await c.delete(
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

            await _retry_on_transient_error(_do_delete, reset_client=True)
            logger.info(
                "Deleted tenant vectors from shared collection",
                tenant_id=str(tenant_id),
            )


async def close_qdrant_connection() -> None:
    """Cierra la conexión con Qdrant."""
    global _qdrant_client, _qdrant_loop_id, _collection_ready
    if _qdrant_client:
        try:
            await _qdrant_client.close()
        except Exception:
            pass
        _qdrant_client = None
        _qdrant_loop_id = None
        _collection_ready = False

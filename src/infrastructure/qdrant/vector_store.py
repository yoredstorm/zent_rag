# =============================================================================
# Qdrant Vector Store Adapter — Búsqueda Semántica Multi-Tenant
# =============================================================================
# Colección única compartida (rag_documents) con filtrado OBLIGATORIO por
# organization_id en payload. Escala a cientos/miles de organizaciones sin
# overhead por colección.
#
# GARANTÍA ANTI-LEAK: search()/upsert() rechazan llamadas sin organization_id
# (ValueError) y TODO filtro incluye MatchValue(organization_id). El filtro
# por knowledge_base_id es opcional (scoping de KB).
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

from src.core.config import get_settings
from src.core.domain.entities import RetrievalChunk, RetrievalContext
from src.core.ports import HybridStore, LexicalStore, VectorStore
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.qdrant.bm25 import encode_sparse, to_sparse_payload
from src.platform.tenants.context import bind_organization_id

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
# True si la colección usa vectores nombrados ("dense" + "sparse").
# Las colecciones legacy (dense anónimo) no soportan búsqueda lexical hasta
# ejecutar el script de migración `migrate_qdrant_hybrid.py`.
_collection_has_named_vectors: bool | None = None


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
            https=settings.QDRANT_HTTPS,
            grpc_port=settings.QDRANT_GRPC_PORT,
            prefer_grpc=False,
            timeout=float(settings.QDRANT_TIMEOUT_SECONDS),
            check_compatibility=False,
        )
        _qdrant_loop_id = current_loop_id
        _collection_ready = False
    return _qdrant_client


def _sparse_index_params() -> qdrant_models.SparseVectorParams:
    """Params sparse con índice en RAM + modifier IDF si el client
    lo soporta (qdrant-client >= 1.13)."""
    index_params = None
    if hasattr(qdrant_models, "SparseIndexParams") and hasattr(
        qdrant_models, "Datatype"
    ):
        index_params = qdrant_models.SparseIndexParams(
            on_disk=False,
            datatype=qdrant_models.Datatype.FLOAT32,
        )
    kwargs: dict[str, object] = {"index": index_params}
    if hasattr(qdrant_models, "Modifier"):
        kwargs["modifier"] = qdrant_models.Modifier.IDF
    return qdrant_models.SparseVectorParams(**kwargs)  # type: ignore[arg-type]


class QdrantVectorStore(VectorStore, LexicalStore, HybridStore):
    """Implementación de VectorStore con colección única compartida.

    Soporta búsqueda semántica (dense), lexical (sparse/BM25) e híbrida
    (RRF server-side) cuando la colección usa vectores nombrados.
    """

    async def _ensure_collection(self) -> None:
        global _collection_ready, _collection_has_named_vectors
        if _collection_ready and _collection_has_named_vectors is not None:
            return
        client = await _get_client()
        settings = get_settings()
        if not await client.collection_exists(RAG_DOCUMENTS_COLLECTION):
            await client.create_collection(
                collection_name=RAG_DOCUMENTS_COLLECTION,
                vectors_config={
                    "dense": qdrant_models.VectorParams(
                        size=settings.VECTOR_DIMENSION,
                        distance=qdrant_models.Distance.COSINE,
                    ),
                },
                # Los vectores sparse con nombre van en su propio campo
                # (qdrant-client >= 1.14): mezclarlos en vectors_config
                # rompe la validación pydantic de CreateCollection.
                sparse_vectors_config={"sparse": _sparse_index_params()},
            )
            _collection_has_named_vectors = True
            logger.info(
                "Created shared vector collection (dense + sparse)",
                collection_name=RAG_DOCUMENTS_COLLECTION,
                vector_dimension=settings.VECTOR_DIMENSION,
            )
        else:
            info = await client.get_collection(RAG_DOCUMENTS_COLLECTION)
            named = getattr(info.config.params.vectors, "size", None) is None
            if _collection_has_named_vectors is None:
                _collection_has_named_vectors = named
                logger.info(
                    "Existing collection detected",
                    named_vectors=bool(named),
                    supports_sparse=bool(named),
                )
            elif _collection_has_named_vectors != named:
                # La colección cambió de forma (migración en vuelo): refrescar.
                _collection_has_named_vectors = named
        _collection_ready = True

    def _build_qdrant_filter(
        self,
        organization_id: UUID,
        filters: dict[str, str] | None,
        exclude_filters: dict[str, str] | None,
        role: str,
        knowledge_base_id: UUID | None,
    ) -> qdrant_models.Filter:
        must_conditions = [
            qdrant_models.FieldCondition(
                key="organization_id",
                match=qdrant_models.MatchValue(value=str(organization_id)),
            )
        ]

        if knowledge_base_id is not None:
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="knowledge_base_id",
                    match=qdrant_models.MatchValue(value=str(knowledge_base_id)),
                )
            )

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

        return qdrant_models.Filter(
            must=must_conditions,  # type: ignore[arg-type]
            must_not=must_not_conditions or None,  # type: ignore[arg-type]
        )

    @staticmethod
    def _chunks_from_points(points: list) -> list[RetrievalChunk]:
        return [
            RetrievalChunk(
                document_id=UUID(point.id) if point.id else UUID(int=0),
                content=point.payload.get("content", "") if point.payload else "",
                score=point.score,
                metadata=point.payload.get("metadata", {}) if point.payload else {},
            )
            for point in points
        ]

    def _ensure_sparse_support(self) -> None:
        if not _collection_has_named_vectors:
            raise RuntimeError(
                "Collection 'rag_documents' lacks sparse vectors. "
                "Run src/scripts/migrate_qdrant_hybrid.py first."
            )

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
    ) -> RetrievalContext:
        if organization_id is None:
            raise ValueError("search() requires organization_id (tenant isolation)")
        organization_id = bind_organization_id(organization_id)
        client = await _get_client()
        await self._ensure_collection()

        start = time.perf_counter()

        qdrant_filter = self._build_qdrant_filter(
            organization_id, filters, exclude_filters, role, knowledge_base_id
        )

        kwargs: dict[str, object] = {
            "collection_name": RAG_DOCUMENTS_COLLECTION,
            "query": query_embedding,
            "limit": top_k,
            "query_filter": qdrant_filter,
            "with_payload": True,
            "score_threshold": score_threshold,
        }
        if _collection_has_named_vectors:
            kwargs["using"] = "dense"

        results = await _retry_on_transient_error(
            client.query_points,
            reset_client=True,
            **kwargs,
        )

        latency_ms = (time.perf_counter() - start) * 1000

        chunks = self._chunks_from_points(results.points)

        logger.info(
            "Vector search completed",
            organization_id=str(organization_id),
            results_count=len(chunks),
            query_latency_ms=round(latency_ms, 2),
            top_score=round(chunks[0].score, 4) if chunks else 0.0,
        )

        return RetrievalContext(
            chunks=chunks,
            query_embedding=query_embedding,
            retrieval_latency_ms=latency_ms,
        )

    async def search_sparse(
        self,
        organization_id: UUID,
        query_text: str,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
        knowledge_base_id: UUID | None = None,
    ) -> RetrievalContext:
        if organization_id is None:
            raise ValueError("search_sparse() requires organization_id (tenant isolation)")
        organization_id = bind_organization_id(organization_id)
        client = await _get_client()
        await self._ensure_collection()
        self._ensure_sparse_support()

        start = time.perf_counter()

        qdrant_filter = self._build_qdrant_filter(
            organization_id, filters, exclude_filters, role, knowledge_base_id
        )

        sparse_vector = encode_sparse(query_text)
        if not sparse_vector:
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)
        indices, values = to_sparse_payload(sparse_vector)
        query = qdrant_models.SparseVector(indices=indices, values=values)

        results = await _retry_on_transient_error(
            client.query_points,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            query=query,
            using="sparse",
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
            score_threshold=score_threshold,
            reset_client=True,
        )

        latency_ms = (time.perf_counter() - start) * 1000
        chunks = self._chunks_from_points(results.points)

        logger.info(
            "Sparse search completed",
            organization_id=str(organization_id),
            results_count=len(chunks),
            query_latency_ms=round(latency_ms, 2),
        )

        return RetrievalContext(
            chunks=chunks,
            retrieval_latency_ms=latency_ms,
        )

    async def search_hybrid(
        self,
        organization_id: UUID,
        query_text: str,
        query_embedding: list[float],
        top_k: int = 5,
        filters: dict[str, str] | None = None,
        exclude_filters: dict[str, str] | None = None,
        score_threshold: float = 0.1,
        role: str = "admin",
        knowledge_base_id: UUID | None = None,
        fusion_weights: dict[str, float] | None = None,
    ) -> RetrievalContext:
        """Fusión RRF server-side (un solo round-trip).

        ADVERTENCIA: el score devuelto es el score RRF (no coseno), por lo
        que el motor prefiere la fusión client-side cuando el gate de
        anti-alucinación depende de scores comparables. Este método existe
        para benchmarks y adaptadores futuros.
        """
        if organization_id is None:
            raise ValueError("search_hybrid() requires organization_id (tenant isolation)")
        organization_id = bind_organization_id(organization_id)
        client = await _get_client()
        await self._ensure_collection()
        self._ensure_sparse_support()

        start = time.perf_counter()

        qdrant_filter = self._build_qdrant_filter(
            organization_id, filters, exclude_filters, role, knowledge_base_id
        )

        sparse_vector = encode_sparse(query_text)
        if not sparse_vector:
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)
        indices, values = to_sparse_payload(sparse_vector)
        sparse_query = qdrant_models.SparseVector(indices=indices, values=values)

        prefetch: list[qdrant_models.Prefetch] = [
            qdrant_models.Prefetch(query=query_embedding, using="dense"),
            qdrant_models.Prefetch(query=sparse_query, using="sparse"),
        ]
        fusion = qdrant_models.FusionQuery(fusion=qdrant_models.Fusion.RRF)

        results = await _retry_on_transient_error(
            client.query_points,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            prefetch=prefetch,
            query=fusion,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
            score_threshold=score_threshold if score_threshold > 0 else 0.0,
            reset_client=True,
        )

        latency_ms = (time.perf_counter() - start) * 1000
        chunks = self._chunks_from_points(results.points)

        logger.info(
            "Hybrid (RRF) search completed",
            organization_id=str(organization_id),
            results_count=len(chunks),
            query_latency_ms=round(latency_ms, 2),
        )

        return RetrievalContext(
            chunks=chunks,
            query_embedding=query_embedding,
            retrieval_latency_ms=latency_ms,
        )

    async def upsert(
        self,
        organization_id: UUID,
        document_id: UUID,
        embedding: list[float],
        content: str,
        metadata: dict[str, str] | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> None:
        await self.upsert_batch(
            organization_id,
            [(document_id, embedding, content, metadata)],
            knowledge_base_id=knowledge_base_id,
        )

    async def upsert_batch(
        self,
        organization_id: UUID,
        points: list[tuple[UUID, list[float], str, dict[str, str] | None]],
        knowledge_base_id: UUID | None = None,
        sparse_vectors: list[dict[str, float]] | None = None,
    ) -> None:
        if not points:
            return
        if organization_id is None:
            raise ValueError("upsert() requires organization_id (tenant isolation)")
        organization_id = bind_organization_id(organization_id)

        if sparse_vectors is not None and len(sparse_vectors) != len(points):
            raise ValueError("sparse_vectors length must match points length")

        async with _upsert_semaphore():
            client = await _get_client()
            await self._ensure_collection()

            structs = []
            for i, (document_id, embedding, content, metadata) in enumerate(points):
                payload = {
                    "content": content,
                    "metadata": metadata or {},
                    "organization_id": str(organization_id),
                    **(
                        {"knowledge_base_id": str(knowledge_base_id)}
                        if knowledge_base_id is not None
                        else {}
                    ),
                }
                if _collection_has_named_vectors:
                    tf = (
                        sparse_vectors[i]
                        if sparse_vectors is not None
                        else encode_sparse(content)
                    )
                    indices, values = to_sparse_payload(tf)
                    vector: object = {
                        "dense": embedding,
                        "sparse": qdrant_models.SparseVector(
                            indices=indices, values=values
                        ),
                    }
                else:
                    vector = embedding
                structs.append(
                    qdrant_models.PointStruct(
                        id=str(document_id),
                        vector=vector,  # type: ignore[arg-type]
                        payload=payload,
                    )
                )

            async def _do_upsert() -> None:
                # Fresh client each retry after reset_client=True
                c = await _get_client()
                await c.upsert(
                    collection_name=RAG_DOCUMENTS_COLLECTION,
                    points=structs,
                    wait=True,
                )

            await _retry_on_transient_error(_do_upsert, reset_client=True)

    async def delete_by_organization(self, organization_id: UUID) -> None:
        """Elimina todos los vectores de una organización por filtro de payload."""
        organization_id = bind_organization_id(organization_id)
        await self._delete_with_filter(
            must=[
                qdrant_models.FieldCondition(
                    key="organization_id",
                    match=qdrant_models.MatchValue(value=str(organization_id)),
                )
            ],
            log_message=f"Deleted organization {organization_id} vectors from shared collection",
        )

    async def delete_by_knowledge_base(
        self, organization_id: UUID, knowledge_base_id: UUID
    ) -> None:
        """Elimina los vectores de una KB (SIEMPRE scoped a su organización)."""
        organization_id = bind_organization_id(organization_id)
        await self._delete_with_filter(
            must=[
                qdrant_models.FieldCondition(
                    key="organization_id",
                    match=qdrant_models.MatchValue(value=str(organization_id)),
                ),
                qdrant_models.FieldCondition(
                    key="knowledge_base_id",
                    match=qdrant_models.MatchValue(value=str(knowledge_base_id)),
                ),
            ],
            log_message=(
                f"Deleted KB {knowledge_base_id} vectors (organization {organization_id})"
            ),
        )

    async def delete_points(self, organization_id: UUID, point_ids: list[str]) -> None:
        """Borra puntos por ID exacto. Los IDs son uuid5 deterministas scoped
        a la organización (generados por el Knowledge Engine desde su registry)."""
        if not point_ids:
            return
        organization_id = bind_organization_id(organization_id)
        async with _upsert_semaphore():
            client = await _get_client()
            await self._ensure_collection()

            async def _do_delete() -> None:
                c = await _get_client()
                await c.delete(
                    collection_name=RAG_DOCUMENTS_COLLECTION,
                    points_selector=qdrant_models.PointIdsList(
                        points=point_ids,
                    ),
                )

            await _retry_on_transient_error(_do_delete, reset_client=True)
            logger.info(
                "Deleted source documents from shared collection",
                organization_id=str(organization_id),
                points_count=len(point_ids),
            )

    async def get_documents(
        self,
        organization_id: UUID,
        document_ids: list[UUID],
        role: str = "admin",
    ) -> RetrievalContext:
        """Fetch por ID con verificación post-hoc de tenant (Qdrant retrieve
        no acepta filtros): cualquier punto cuyo payload no pertenezca a la
        organización (o no sea visible para el rol) se descarta."""
        if organization_id is None:
            raise ValueError("get_documents() requires organization_id (tenant isolation)")
        organization_id = bind_organization_id(organization_id)
        if not document_ids:
            return RetrievalContext(chunks=[], retrieval_latency_ms=0.0)
        client = await _get_client()
        await self._ensure_collection()

        start = time.perf_counter()
        results = await _retry_on_transient_error(
            client.retrieve,
            collection_name=RAG_DOCUMENTS_COLLECTION,
            ids=[str(doc_id) for doc_id in document_ids],
            with_payload=True,
            with_vectors=False,
            reset_client=True,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        chunks: list[RetrievalChunk] = []
        for point in results:
            payload = point.payload or {}
            if payload.get("organization_id") != str(organization_id):
                logger.warning(
                    "Cross-tenant document fetch blocked",
                    document_id=str(point.id),
                    requested_by=str(organization_id),
                )
                continue
            if role == "customer" and payload.get("metadata", {}).get("visibility") != "public":
                continue
            chunks.append(
                RetrievalChunk(
                    document_id=UUID(point.id) if point.id else UUID(int=0),
                    content=payload.get("content", ""),
                    score=0.0,
                    metadata=payload.get("metadata", {}),
                )
            )

        logger.info(
            "Documents fetched by id",
            organization_id=str(organization_id),
            requested=len(document_ids),
            returned=len(chunks),
            latency_ms=round(latency_ms, 2),
        )
        return RetrievalContext(
            chunks=chunks,
            retrieval_latency_ms=latency_ms,
        )

    async def _delete_with_filter(self, *, must: list, log_message: str) -> None:
        async with _upsert_semaphore():
            client = await _get_client()
            await self._ensure_collection()

            async def _do_delete() -> None:
                c = await _get_client()
                await c.delete(
                    collection_name=RAG_DOCUMENTS_COLLECTION,
                    points_selector=qdrant_models.FilterSelector(
                        filter=qdrant_models.Filter(must=must)
                    ),
                )

            await _retry_on_transient_error(_do_delete, reset_client=True)
            logger.info(log_message)


async def close_qdrant_connection() -> None:
    """Cierra la conexión con Qdrant."""
    global _qdrant_client, _qdrant_loop_id, _collection_ready, _collection_has_named_vectors
    if _qdrant_client:
        try:
            await _qdrant_client.close()
        except Exception:
            pass
        _qdrant_client = None
        _qdrant_loop_id = None
        _collection_ready = False
        _collection_has_named_vectors = None

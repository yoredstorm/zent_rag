# =============================================================================
# Knowledge Ingestion Engine — orquestador genérico (sin dominio vertical)
# =============================================================================
# Flujo por job:
#   pending -> running -> completed | failed ->(retry_at)-> pending
#             failed -(attempts >= max_attempts)-> dead
#
# - Retry: backoff exponencial (compute_retry_delay).
# - Resume: cursor_snapshot persiste el checkpoint; el conector lo retoma.
# - Dead letter: el job queda en 'dead' con error_summary y su historial en
#   ingestion_job_errors (nunca se pierde).
# - Update/delete detection: registry source_documents + delete de vectores
#   huérfanos por ID exacto.
# =============================================================================
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from src.core.domain.entities import (
    IngestionJob,
    IngestionJobStatus,
    KnowledgeBase,
)
from src.core.ports import (
    DocumentRegistryRepository,
    EmbeddingProvider,
    IngestionJobRepository,
    KnowledgeBaseRepository,
    SourceRepository,
    SyncStateRepository,
    VectorStore,
)
from src.knowledge.connectors.base import ConnectorError, Record
from src.knowledge.connectors.registry import build_connector
from src.rag.chunking.registry import get_chunker

logger = logging.getLogger(__name__)

# Namespace determinista para IDs de documentos (uuid5)
_DOC_NS = UUID("6f9e0d4a-8a7b-4c3e-9f1e-2b5c8d7a6f90")

# Chunking por defecto si la fuente no pertenece a una KB
DEFAULT_CHUNK_STRATEGY = "fixed"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 150

_CHECKPOINT_EVERY = 10  # records entre updates de progreso
_EMBED_BATCH = 32  # chunks por llamada de embedding


def compute_retry_delay(attempt: int, base_seconds: int = 10, cap_seconds: int = 300) -> int:
    """Backoff exponencial: base * 2^(attempt-1), acotado a cap."""
    return min(base_seconds * (2 ** max(attempt - 1, 0)), cap_seconds)


def _chunk_document_id(source_id: UUID, external_id: str, chunk_index: int) -> UUID:
    return uuid5(_DOC_NS, f"{source_id}:{external_id}:{chunk_index}")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _validate_metadata(
    metadata: dict, schema: dict | None
) -> tuple[dict, str | None]:
    """Aplica el metadata_schema de la KB. Retorna (metadata_limpio, error)."""
    fields = (schema or {}).get("fields") or {}
    if not fields:
        return dict(metadata), None
    cleaned: dict = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            continue
        expected = spec.get("type", "str")
        required = bool(spec.get("required", False))
        if name not in metadata:
            if required:
                return {}, f"missing required metadata field '{name}'"
            continue
        value = metadata[name]
        try:
            if expected == "int":
                value = int(value)
            elif expected == "float":
                value = float(value)
            elif expected == "bool":
                value = bool(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            return {}, f"metadata field '{name}' must be {expected}"
        cleaned[name] = value
    return cleaned, None


class KnowledgeIngestionEngine:
    """Motor de ingestion de la Knowledge Platform."""

    def __init__(
        self,
        job_repo: IngestionJobRepository,
        sync_state_repo: SyncStateRepository,
        doc_registry_repo: DocumentRegistryRepository,
        kb_repo: KnowledgeBaseRepository,
        source_repo: SourceRepository,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        *,
        backoff_base_seconds: int = 10,
        max_attempts_default: int = 3,
    ) -> None:
        self._jobs = job_repo
        self._state = sync_state_repo
        self._registry = doc_registry_repo
        self._kbs = kb_repo
        self._sources = source_repo
        self._vectors = vector_store
        self._embeddings = embedding_provider
        self._backoff_base = backoff_base_seconds
        self._max_attempts_default = max_attempts_default

    # ------------------------------------------------------------------
    # Entry point del worker
    # ------------------------------------------------------------------
    async def execute_job(self, job_id: UUID) -> IngestionJob:
        job = await self._jobs.get_job(None, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if job.is_terminal:
            return job

        await self._jobs.update_job(
            job_id,
            status=IngestionJobStatus.RUNNING.value,
            attempts=job.attempts + 1,
            started_at=datetime.now(timezone.utc),
        )
        job = await self._jobs.get_job(None, job_id)

        try:
            await self._run(job)
        except Exception as exc:
            await self._handle_failure(job_id, job, exc)
        return await self._jobs.get_job(None, job_id)

    async def _handle_failure(self, job_id: UUID, job: IngestionJob, exc: Exception) -> None:
        error_text = f"{type(exc).__name__}: {exc}"[:2000]
        await self._jobs.record_error(job_id, job.attempts, error_text)

        if job.attempts >= (job.max_attempts or self._max_attempts_default):
            await self._jobs.update_job(
                job_id,
                status=IngestionJobStatus.DEAD.value,
                completed_at=datetime.now(timezone.utc),
                error_summary={
                    "error": error_text,
                    "attempts": job.attempts,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
        else:
            delay = compute_retry_delay(job.attempts, self._backoff_base)
            await self._jobs.update_job(
                job_id,
                status=IngestionJobStatus.FAILED.value,
                retry_at=datetime.now(timezone.utc) + timedelta(seconds=delay),
                error_summary={
                    "error": error_text,
                    "attempts": job.attempts,
                    "retry_at_seconds": delay,
                },
            )
        if job.source_id:
            await self._state.save_state(
                job.source_id,
                error=error_text,
                success=False,
            )

    # ------------------------------------------------------------------
    # Flujo principal
    # ------------------------------------------------------------------
    async def _run(self, job: IngestionJob) -> None:
        source = await self._sources.get_source(job.organization_id, job.source_id) if job.source_id else None
        if source is None:
            raise ConnectorError(f"Source {job.source_id} not found for this organization")

        kb: KnowledgeBase | None = None
        if job.knowledge_base_id:
            kb = await self._kbs.get_kb(job.organization_id, job.knowledge_base_id)

        connector = build_connector(source)
        await connector.connect()
        await connector.validate()

        state = await self._state.get_state(source.id)
        cursor = job.cursor_snapshot if job.cursor_snapshot is not None else (state.cursor if state else None)

        if connector.self_contained:
            outcome = await connector.sync(cursor)
            await self._jobs.update_job(
                job.id,
                records_processed=job.records_processed + outcome.records_processed,
                records_failed=job.records_failed + outcome.records_failed,
                progress=100,
            )
            await self._state.save_state(
                source.id,
                cursor=outcome.cursor,
                error="; ".join(outcome.errors[:3]) or None,
                processed_count=outcome.records_processed,
                success=not outcome.errors,
            )
        else:
            await self._run_record_mode(job, source.id, connector, kb, cursor)

        await self._jobs.update_job(
            job.id,
            status=IngestionJobStatus.COMPLETED.value,
            progress=100,
            completed_at=datetime.now(timezone.utc),
        )

    async def _run_record_mode(self, job, source_id: UUID, connector, kb, cursor) -> None:
        chunker = get_chunker(
            kb.chunking_strategy if kb else DEFAULT_CHUNK_STRATEGY,
            chunk_size=kb.chunk_size if kb else DEFAULT_CHUNK_SIZE,
            chunk_overlap=kb.chunk_overlap if kb else DEFAULT_CHUNK_OVERLAP,
        )
        schema = kb.metadata_schema if kb else None

        records_processed = 0
        records_failed = 0
        seen_external_ids: set[str] = set()
        pending_chunks: list[tuple[str, str]] = []  # (external_id, chunk_text)
        chunk_indexes: dict[str, int] = {}

        def next_index(external_id: str) -> int:
            index = chunk_indexes.get(external_id, 0)
            chunk_indexes[external_id] = index + 1
            return index

        async def flush() -> None:
            if not pending_chunks:
                return
            texts = [t for _, t in pending_chunks]
            embeddings = await self._embeddings.embed(texts, model=kb.embedding_model if kb else None)
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]  # provider devolvió un solo vector
            points: list[tuple[UUID, list[float], str, dict | None]] = []
            for (external_id, text), vector in zip(pending_chunks, embeddings):
                chunk_index = next_index(external_id)
                doc_id = _chunk_document_id(source_id, external_id, chunk_index)
                points.append(
                    (
                        doc_id,
                        list(vector),
                        text,
                        {
                            "source_id": str(source_id),
                            "external_id": external_id,
                            "content_hash": _content_hash(text),
                            "chunking_strategy": chunker.__class__.__name__,
                            "organization_id": str(job.organization_id),
                            **({"knowledge_base_id": str(job.knowledge_base_id)} if job.knowledge_base_id else {}),
                        },
                    )
                )
                await self._registry.upsert_document(
                    job.organization_id,
                    source_id,
                    f"{external_id}#{chunk_index}",
                    doc_id,
                    _content_hash(text),
                )
            await self._vectors.upsert_batch(
                job.organization_id, points, knowledge_base_id=job.knowledge_base_id
            )
            pending_chunks.clear()

        record: Record
        async for record in connector.iter_records(cursor):
            seen_external_ids.add(record.external_id)
            clean_metadata, error = _validate_metadata(record.metadata, schema)
            if error:
                records_failed += 1
                continue
            chunks = chunker.chunk(record.content)
            if not chunks:
                records_failed += 1
                continue
            for text in chunks:
                pending_chunks.append((record.external_id, text))
            if len(pending_chunks) >= _EMBED_BATCH:
                await flush()

            records_processed += 1
            if records_processed % _CHECKPOINT_EVERY == 0:
                final_cursor = getattr(connector, "_last_cursor", None)
                await self._jobs.update_job(
                    job.id,
                    records_processed=records_processed,
                    records_failed=records_failed,
                    progress=50,  # progreso indeterminado hasta terminar
                    cursor_snapshot=final_cursor if final_cursor is not None else job.cursor_snapshot,
                )

        await flush()

        # Delete detection: registry marca 'deleted' lo no visto y retorna ids
        deleted = await self._registry.mark_missing_deleted(source_id, seen_external_ids)
        if deleted:
            ids = [str(d) for d in deleted]
            await self._vectors.delete_points(job.organization_id, ids)

        final_cursor = getattr(connector, "_last_cursor", None)
        await self._state.save_state(
            source_id,
            cursor=final_cursor or cursor,
            processed_count=records_processed,
            success=True,
        )
        await self._jobs.update_job(
            job.id,
            records_processed=records_processed,
            records_failed=records_failed,
            progress=100,
        )

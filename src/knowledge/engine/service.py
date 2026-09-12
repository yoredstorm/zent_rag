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
from src.core.ports.structured import StructuredDocumentRepository
from src.infrastructure.observability.logging_config import get_logger
from src.knowledge.connectors.base import ConnectorError, Record
from src.knowledge.connectors.registry import build_connector
from src.rag.chunking.registry import get_chunker

# structlog (kwargs-safe). El stdlib logger revienta con logging(key=value).
logger = get_logger(__name__)

# Namespace determinista para IDs de documentos (uuid5)
_DOC_NS = UUID("6f9e0d4a-8a7b-4c3e-9f1e-2b5c8d7a6f90")
# Namespace V2 (Phase C): separado del ns V1 para que los IDs de chunk V2
# nunca colisionen con los chunks V1 (misma colección Qdrant).
_V2_CHUNK_NS = UUID("c7a2e5d9-4b3f-4a1c-9d8e-6f5b2a4e8c10")

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


def _v2_chunk_id(source_id: UUID, external_id: str, chunk_index: int) -> UUID:
    return uuid5(_V2_CHUNK_NS, f"v2:{source_id}:{external_id}:{chunk_index}")


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
        structured_doc_repo: StructuredDocumentRepository | None = None,
        summarizer: object | None = None,
        usage_tracker: object | None = None,
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
        # Knowledge V2 (Phase B): paralelo, opcional, nunca rompe el camino V1.
        self._structured_v2 = structured_doc_repo
        # Phase C3: summarizer shadow (mode=shadow) — calcula, NO persiste.
        self._summarizer = summarizer
        # Phase G (brief §41): registro de costos por corpus/source.
        self._usage_tracker = usage_tracker
        self.v2_parsed = 0
        self.v2_failed = 0

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
            await self._run_record_mode(job, source, connector, kb, cursor)

        await self._jobs.update_job(
            job.id,
            status=IngestionJobStatus.COMPLETED.value,
            progress=100,
            completed_at=datetime.now(timezone.utc),
        )

    async def _run_record_mode(self, job, source, connector, kb, cursor) -> None:
        source_id = source.id
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
            await self._maybe_structured_v2(job, source, record)
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

    async def _maybe_structured_v2(self, job, source, record: Record) -> None:
        """Phase B: parsea a StructuredDocument y persiste EN PARALELO a V1.

        Nunca interrumpe el camino V1: errores de parseo/persistencia son warn
        y se contabilizan (v2_failed). Requiere que el conector entregue los
        bytes originales (record.raw_data + record.format).
        """
        if self._structured_v2 is None:
            return
        raw_data = record.raw_data
        record_format = record.format
        if raw_data is None or not record_format:
            return

        from src.knowledge.structure import get_parser

        parser = get_parser(record_format)
        if parser is None:
            return

        import time

        from src.infrastructure.observability.metrics import (
            knowledge_parse_latency,
            knowledge_parse_total,
        )

        started = time.perf_counter()
        outcome = "parse_error"
        try:
            document = parser.parse(
                raw_data,
                organization_id=job.organization_id,
                external_id=record.external_id,
                source_id=source.id,
                workspace_id=source.workspace_id,
                source_name=str(record.metadata.get("filename") or record.external_id),
            )
            document.check_consistency()
            outcome = "persist_error"
            change_kind = await self._structured_v2.upsert_document(document)
            logger.info(
                "Knowledge V2 document upserted",
                document_id=str(document.id),
                external_id=document.external_id,
                change_kind=change_kind or "unknown",
            )
            outcome = "chunk_index"
            await self._index_v2_chunks(job, source, document, change_kind=change_kind)
            outcome = "summarize"
            await self._shadow_summarize(document, change_kind=change_kind)
            outcome = "ok"
            self.v2_parsed += 1
        except Exception as exc:
            self.v2_failed += 1
            logger.warning(
                "Knowledge V2 structured pipeline failed",
                external_id=record.external_id,
                stage=outcome,
                error=str(exc)[:500],
            )
        finally:
            knowledge_parse_total.labels(
                organization_id=str(job.organization_id),
                format=record_format,
                outcome=outcome,
            ).inc()
            knowledge_parse_latency.labels(
                organization_id=str(job.organization_id),
                format=record_format,
            ).observe(time.perf_counter() - started)

    async def _index_v2_chunks(
        self, job, source, document, *, change_kind: str | None = None
    ) -> None:
        """Phase C: embebe los child chunks V2 y los upserta en Qdrant.

        Dual-write aditivo: misma colección rag_documents y MISMO contrato ACL
        (organization_id en payload). Los chunk_ids usan el namespace V2 para
        no colisionar con los de V1. Fallos aquí son warn (v2_failed); el
        documento estructurado ya quedó persistido en Postgres.

        Fingerprinting (§41): contenido sin cambios (change_kind=unchanged) →
        chunks idénticos → se SKIPEA el re-embed y se registra la decisión.
        """
        from src.knowledge.structure import (
            ChunkingConfig as _ChunkingConfig,
        )
        from src.knowledge.structure import (
            ChunkType as _ChunkType,
        )
        from src.knowledge.structure import (
            chunk_structured_document as _chunk_structured_document,
        )

        chunks = _chunk_structured_document(document, config=_ChunkingConfig())
        children = [c for c in chunks if c.chunk_type is _ChunkType.PARENT_CHILD]
        if not children:
            return
        if change_kind == "unchanged":
            logger.info(
                "Knowledge V2 chunks skipped (content unchanged — fingerprint)",
                document_id=str(document.id),
                chunks=len(children),
            )
            return

        knowledge_base_id = job.knowledge_base_id
        for start in range(0, len(children), _EMBED_BATCH):
            batch_chunks = children[start : start + _EMBED_BATCH]
            embeddings = await self._embeddings.embed(
                [c.content for c in batch_chunks]
            )
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]
            if self._usage_tracker is not None:
                try:
                    batch_tokens = sum(c.token_count for c in batch_chunks)
                    await self._usage_tracker.record_embedding_tokens(
                        job.organization_id,
                        batch_tokens,
                        workspace_id=source.workspace_id,
                        source_id=source.id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge V2 usage tracking failed",
                        error=str(exc)[:200],
                    )
            points: list[tuple[UUID, list[float], str, dict | None]] = []
            for chunk, vector in zip(batch_chunks, embeddings):
                # Campos estructurales DENTRO de metadata (contrato del adapter:
                # RetrievalChunk.metadata = payload["metadata"]; ACL por defecto
                # org-wide igual que los chunks V1).
                chunk_metadata: dict = {
                    "source_id": str(source.id),
                    "external_id": document.external_id,
                    "content_hash": chunk.content_hash,
                    "chunking_strategy": "document_structure+parent_child",
                    "chunk_type": chunk.chunk_type.value,
                    "workspace_id": (
                        str(source.workspace_id) if source.workspace_id else None
                    ),
                    "knowledge_base_id": (
                        str(knowledge_base_id) if knowledge_base_id else None
                    ),
                    "document_id": str(document.id),
                    "section_id": str(chunk.section_id) if chunk.section_id else None,
                    "parent_id": str(chunk.parent_id) if chunk.parent_id else None,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "v2_chunk": "true",
                }
                points.append(
                    (
                        _v2_chunk_id(source.id, document.external_id, chunk.chunk_index),
                        list(vector),
                        chunk.content,
                        chunk_metadata,
                    )
                )
            await self._vectors.upsert_batch(
                job.organization_id, points, knowledge_base_id=knowledge_base_id
            )

    async def _shadow_summarize(self, document, *, change_kind: str | None = None) -> None:
        """Phase C3 shadow: calcula SectionSummary/DocumentSummary (INFERRED).

        No persiste nada; sirve de calibración (métricas + logs). Si el
        summarizer no está inyectado o falla, el camino V1/V2 sigue intacto.
        Con change_kind=unchanged se SKIPEA (mismo contenido → mismo resumen).
        """
        if self._summarizer is None:
            return
        if change_kind == "unchanged":
            logger.info(
                "Knowledge V2 summaries skipped (content unchanged)",
                document_id=str(document.id),
            )
            return
        try:
            output = await self._summarizer.summarize(document)
            summary = getattr(output, "document_summary", None)
            summary_text = getattr(summary, "summary", "") if summary else ""
            logger.info(
                "Knowledge V2 summary shadow computed",
                document_id=str(document.id),
                summary_chars=len(summary_text[:2000]),
                mode=getattr(output, "mode", "unknown"),
            )
        except Exception as exc:
            logger.warning(
                "Knowledge V2 summary shadow failed",
                document_id=str(document.id),
                error=str(exc)[:500],
            )


async def _set_source_status(organization_id: UUID, source_id: UUID, status: str) -> None:
    """Actualiza el estado del ciclo de vida de la fuente (fail-silent)."""
    from sqlalchemy import text as _text

    from src.infrastructure.postgres.session import get_async_session

    try:
        session = await get_async_session()
        try:
            await session.execute(
                _text(
                    "UPDATE kb_sources SET status = :status, updated_at = NOW() "
                    "WHERE id = :sid AND organization_id = :oid"
                ),
                {"status": status, "sid": source_id, "oid": organization_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    except Exception:
        logger.warning("Failed to update source status", source_id=str(source_id))

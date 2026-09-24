# =============================================================================
# Knowledge Ingestion Engine — orquestador genérico (sin dominio vertical)
# =============================================================================
# Flujo por job:
#   pending -> running -> completed | failed ->(retry_at)-> pending
#             failed -(attempts >= max_attempts)-> dead
#
# - Retry: backoff exponencial (compute_retry_delay). 429/RateLimitError
#   usa base 60s (cap 900s) y honra Retry-After si es más largo.
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
from src.core.ports.tabular import TabularRepository
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


RATE_LIMIT_BACKOFF_BASE_SECONDS = 60
RATE_LIMIT_BACKOFF_CAP_SECONDS = 900

_RATE_LIMIT_MARKERS = (
    "ratelimiterror",
    "error code: 429",
    "status code: 429",
    "httpstatuserror: 429",
    "server overload",
    "too many requests",
)


def compute_retry_delay(attempt: int, base_seconds: int = 10, cap_seconds: int = 300) -> int:
    """Backoff exponencial: base * 2^(attempt-1), acotado a cap."""
    return min(base_seconds * (2 ** max(attempt - 1, 0)), cap_seconds)


def is_rate_limit_error(exc: BaseException) -> bool:
    """True si el fallo es saturación/cuota del proveedor (429 / RateLimitError)."""
    name = type(exc).__name__.lower()
    if "ratelimit" in name or name in {"toomanyrequests", "resourceexhausted"}:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def retry_after_seconds(exc: BaseException) -> int | None:
    """Lee Retry-After (segundos) del response/headers del exception, si existe."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) if response is not None else None
    if headers is None:
        headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = None
    getter = getattr(headers, "get", None)
    if callable(getter):
        raw = getter("Retry-After") or getter("retry-after")
    elif isinstance(headers, dict):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 1 else None


def compute_failure_retry_delay(
    exc: BaseException,
    attempt: int,
    *,
    base_seconds: int = 10,
    cap_seconds: int = 300,
) -> int:
    """Backoff del job: 429 espera más (60s+) o el Retry-After del proveedor."""
    if is_rate_limit_error(exc):
        exponential = compute_retry_delay(
            attempt,
            base_seconds=RATE_LIMIT_BACKOFF_BASE_SECONDS,
            cap_seconds=RATE_LIMIT_BACKOFF_CAP_SECONDS,
        )
        extra = retry_after_seconds(exc)
        if extra is None:
            return exponential
        return min(max(exponential, extra), RATE_LIMIT_BACKOFF_CAP_SECONDS)
    return compute_retry_delay(attempt, base_seconds=base_seconds, cap_seconds=cap_seconds)


def _chunk_document_id(source_id: UUID, external_id: str, chunk_index: int) -> UUID:
    return uuid5(_DOC_NS, f"{source_id}:{external_id}:{chunk_index}")


def _v2_chunk_id(source_id: UUID, external_id: str, chunk_index: int) -> UUID:
    return uuid5(_V2_CHUNK_NS, f"v2:{source_id}:{external_id}:{chunk_index}")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _acl_payload(metadata: dict) -> dict:
    """Copia los campos ACL del record al payload de Qdrant (filtro pre-LLM).

    Solo incluye claves presentes; `upsert_batch` aplica defaults org-wide
    cuando faltan (mismo contrato para V1 y V2)."""
    acl: dict = {}
    visibility = metadata.get("visibility")
    if visibility:
        acl["visibility"] = str(visibility)
    for key in ("acl_users", "acl_groups"):
        values = metadata.get(key)
        if values:
            acl[key] = [str(v) for v in values]
    return acl


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

    @staticmethod
    async def _embedding_cost(model: str | None, tokens: int) -> float:
        """Costo real de los tokens de embedding (antes quedaba en 0)."""
        if tokens <= 0:
            return 0.0
        try:
            from src.platform.billing.pricing import estimate_cost

            settings = None
            try:
                from src.core.config import get_settings

                settings = get_settings()
            except Exception:  # noqa: BLE001
                settings = None
            usado = model or getattr(settings, "EMBEDDING_MODEL", "") or "embeddings/default"
            return float(
                await estimate_cost(usado, 0, 0, embedding_tokens=tokens)
            )
        except Exception as exc:  # noqa: BLE001 — el costo nunca rompe la ingesta
            logger.warning("Embedding cost estimate failed", error=str(exc)[:150])
            return 0.0

    @staticmethod
    def _observe_ingest(kind: str, tokens: int, cost_usd: float) -> None:
        """Métrica de ingesta: tokens y costo por tipo (nunca rompe la ingesta)."""
        try:
            from src.infrastructure.observability.metrics import (
                knowledge_ingest_cost_usd,
                knowledge_ingest_tokens_total,
            )

            knowledge_ingest_tokens_total.labels(kind=kind).inc(max(int(tokens), 0))
            knowledge_ingest_cost_usd.labels(kind=kind).inc(max(float(cost_usd), 0.0))
        except Exception:  # noqa: BLE001
            return

    @staticmethod
    async def _record_ingest_usage_event(
        *,
        organization_id: UUID,
        job_id: UUID,
        kind: str,
        tokens: int,
        cost_usd: float,
        index: int,
        source_id: UUID | None = None,
        model: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        """Evento canónico de uso (aparece en /billing/usage y FinOps).

        `request_id` determinista: un reintento del mismo job no doble-cuenta.
        """
        if tokens <= 0:
            return
        try:
            from uuid import NAMESPACE_URL, uuid5

            from src.platform.usage.usage_engine import (
                UsageEvent,
                get_usage_counters,
                record_event,
            )

            request_id = uuid5(
                NAMESPACE_URL, f"knowledge:{job_id}:{source_id}:{kind}:{index}"
            )
            event = UsageEvent(
                request_id=request_id,
                organization_id=organization_id,
                event_type=f"knowledge_ingest_{kind}",
                model=model,
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(tokens),
                embedding_tokens=int(tokens) if kind == "embedding" else 0,
                estimated_cost=float(cost_usd),
                cost_tags={
                    "origin": "knowledge_ingest",
                    "kind": kind,
                    "source_id": str(source_id) if source_id else "",
                },
            )
            if await record_event(event):
                await get_usage_counters().record(
                    organization_id,
                    request_id,
                    tokens=int(tokens),
                    cost=float(cost_usd),
                )
        except Exception as exc:  # noqa: BLE001 — el metering nunca rompe la ingesta
            logger.warning("Knowledge ingest usage event failed", error=str(exc)[:200])

    @staticmethod
    def _embed_texts(texts: list[str]) -> list[str]:
        """Recorta lo que se manda a embeber, sin tocar el contenido del chunk.

        Un chunk padre puede tener decenas de miles de caracteres (una sección
        entera de un manual) y eso excede el límite del modelo de embeddings: el
        provider devuelve 400 y se cae TODO el pipeline V2 del documento.
        """
        try:
            from src.core.config import get_settings

            tope = int(getattr(get_settings(), "RAG_EMBED_MAX_CHARS", 6000) or 0)
        except Exception:  # noqa: BLE001
            tope = 6000
        if tope <= 0:
            return texts
        return [texto[:tope] for texto in texts]

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
        tabular_repo: TabularRepository | None = None,
        summarizer: object | None = None,
        usage_tracker: object | None = None,
        company_discovery: object | None = None,
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
        # Knowledge Tabular V2: representación estructurada de Excel/CSV.
        self._tabular_v2 = tabular_repo
        # Phase C3: summarizer shadow (mode=shadow) — calcula, NO persiste.
        self._summarizer = summarizer
        # Phase G (brief §41): registro de costos por corpus/source.
        self._usage_tracker = usage_tracker
        # Fase 5B: hook opcional de descubrimiento de compañía (fail-soft).
        self._company_discovery = company_discovery
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
            if job.source_id:
                await _set_source_status(job.organization_id, job.source_id, "indexed")
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
            delay = compute_failure_retry_delay(
                exc, job.attempts, base_seconds=self._backoff_base
            )
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
            await _set_source_status(job.organization_id, job.source_id, "error")

    # ------------------------------------------------------------------
    # Flujo principal
    # ------------------------------------------------------------------
    async def _run(self, job: IngestionJob) -> None:
        source = await self._sources.get_source(job.organization_id, job.source_id) if job.source_id else None
        if source is None:
            raise ConnectorError(f"Source {job.source_id} not found for this organization")

        await _set_source_status(job.organization_id, source.id, "ingesting")

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
        # Knowledge V2/Tabular: external_ids de documentos estructurados
        # (un workbook Excel/CSV produce un documento, no un record por fila).
        v2_external_ids: set[str] = set()
        pending_chunks: list[tuple[str, str]] = []  # (external_id, chunk_text)
        chunk_indexes: dict[str, int] = {}
        flush_index = 0  # índice estable de lote (idempotencia del evento de uso)

        def next_index(external_id: str) -> int:
            index = chunk_indexes.get(external_id, 0)
            chunk_indexes[external_id] = index + 1
            return index

        async def flush() -> None:
            nonlocal flush_index
            if not pending_chunks:
                return
            flush_index += 1
            texts = self._embed_texts([t for _, t in pending_chunks])
            embeddings = await self._embeddings.embed(texts, model=kb.embedding_model if kb else None)
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]  # provider devolvió un solo vector
            if self._usage_tracker is not None:
                # Gap de observabilidad cerrado: el camino V1 también registra
                # tokens de embedding (antes solo lo hacía V2).
                try:
                    from src.knowledge.structure.base import token_count as _tokens

                    batch_tokens = sum(_tokens(text) for text in texts)
                    modelo = kb.embedding_model if kb else None
                    costo = await self._embedding_cost(modelo, batch_tokens)
                    await self._usage_tracker.record_embedding_tokens(
                        job.organization_id,
                        batch_tokens,
                        model=modelo,
                        cost_usd=costo,
                        workspace_id=source.workspace_id,
                        source_id=source_id,
                    )
                    self._observe_ingest("embedding", batch_tokens, costo)
                    await self._record_ingest_usage_event(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        kind="embedding",
                        tokens=batch_tokens,
                        cost_usd=costo,
                        index=flush_index,
                        source_id=source_id,
                        model=modelo,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge usage tracking (V1 embeddings) failed",
                        error=str(exc)[:200],
                    )
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
                            **_acl_payload(record.metadata),
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
            await self._maybe_structured_v2(job, source, record, v2_external_ids)
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

        # Delete detection: registry marca 'deleted' lo no visto y retorna ids.
        # El keep-set incluye los documentos estructurados V2/Tabular (workbook
        # completo) además de los records V1.
        keep_external_ids = seen_external_ids | v2_external_ids
        deleted = await self._registry.mark_missing_deleted(source_id, keep_external_ids)
        if deleted:
            ids = [str(d) for d in deleted]
            await self._vectors.delete_points(job.organization_id, ids)

        # F5: purga V2 (Qdrant + Postgres) de documentos que ya no existen en
        # la fuente. La lista `keep_external_ids` define qué queda vivo.
        if self._structured_v2 is not None:
            try:
                await self._vectors.delete_stale_v2_documents(
                    job.organization_id, source_id, keep_external_ids
                )
                await self._structured_v2.delete_missing_documents(
                    job.organization_id, source_id, keep_external_ids
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Knowledge V2 stale purge failed",
                    source_id=str(source_id),
                    error=str(exc)[:300],
                )
        if self._tabular_v2 is not None:
            try:
                await self._tabular_v2.delete_missing_workbooks(
                    job.organization_id, source_id, v2_external_ids
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Knowledge Tabular stale purge failed",
                    source_id=str(source_id),
                    error=str(exc)[:300],
                )

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

    async def _maybe_structured_v2(
        self,
        job,
        source,
        record: Record,
        v2_external_ids: set[str] | None = None,
    ) -> None:
        """Phase B: parsea a StructuredDocument y persiste EN PARALELO a V1.

        Nunca interrumpe el camino V1: errores de parseo/persistencia son warn
        y se contabilizan (v2_failed). Requiere que el conector entregue los
        bytes originales (record.raw_data + record.format).

        Knowledge Tabular V2: si el documento trae árbol tabular (Excel/CSV),
        se persiste la representación estructurada y los chunks se generan con
        TabularChunker (multinivel) en lugar del chunker de secciones.
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

        # El conector puede declarar el external_id del documento (una sola
        # vez por archivo) aunque el record sea la fila N.
        external_id = str(
            record.metadata.get("document_external_id") or record.external_id
        )
        started = time.perf_counter()
        outcome = "parse_error"
        try:
            document = parser.parse(
                raw_data,
                organization_id=job.organization_id,
                external_id=external_id,
                source_id=source.id,
                workspace_id=source.workspace_id,
                source_name=str(record.metadata.get("filename") or external_id),
            )
            document.check_consistency()
            outcome = "persist_error"
            change_kind = await self._structured_v2.upsert_document(document)
            if v2_external_ids is not None:
                v2_external_ids.add(external_id)
            logger.info(
                "Knowledge V2 document upserted",
                document_id=str(document.id),
                external_id=external_id,
                change_kind=change_kind or "unknown",
                tabular=document.tabular is not None,
            )
            outcome = "chunk_index"
            tabular_diff = await self._persist_tabular_v2(
                job, source, document, change_kind=change_kind
            )
            index_result = await self._index_v2_chunks(
                job, source, document, change_kind=change_kind,
                acl=_acl_payload(record.metadata),
                tabular_diff=tabular_diff,
            )
            if index_result and self._tabular_v2 is not None and document.tabular is not None:
                try:
                    policy = self._chunking_policy_key(self._tabular_chunking_config())
                    await self._tabular_v2.set_runtime_metadata(
                        job.organization_id,
                        document.tabular.id,
                        {
                            "chunking_policy": policy,
                            "chunk_count": int(index_result),
                        },
                    )
                    await self._tabular_v2.set_representations(
                        job.organization_id,
                        document.tabular.id,
                        {
                            "structured": True,
                            "semantic": True,
                            "lexical": True,
                        },
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge Tabular representations update failed",
                        error=str(exc)[:200],
                    )
            outcome = "summarize"
            await self._shadow_summarize(document, change_kind=change_kind)
            await self._maybe_discover_company(
                job, source, document, change_kind=change_kind
            )
            outcome = "ok"
            self.v2_parsed += 1
        except Exception as exc:
            self.v2_failed += 1
            logger.warning(
                "Knowledge V2 structured pipeline failed",
                external_id=external_id,
                stage=outcome,
                error=str(exc)[:500],
            )
            # Si falló DESPUÉS de persistir el documento, el hash nuevo ya quedó
            # guardado y el próximo sync lo vería "unchanged" sin haber indexado
            # nada: se marca para reindexar.
            if outcome not in ("parse", "persist"):
                try:
                    await self._structured_v2.invalidate_content_hash(
                        job.organization_id, document.id
                    )
                except Exception as inner:  # noqa: BLE001 — nunca tapar el error real
                    logger.warning(
                        "Knowledge V2 reindex mark failed", error=str(inner)[:200]
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

    @staticmethod
    def _chunking_policy_key(config) -> str:
        """Hash de la política de chunking tabular (invalida puntos al cambiar)."""
        import hashlib
        import json

        payload = {
            "rv": 3,  # v3: KEY corto + columnas cortas (posiciones) en grupos
            "rg": config.row_group_size,
            "rgo": config.row_group_overlap,
            "gr": config.max_group_rows,
            "kc": config.key_columns_for_wide_tables,
            "wt": config.wide_table_columns,
            "mkc": config.max_group_key_columns,
            "ft": config.max_free_text_chars_in_groups,
            "rows": config.max_embedding_rows_per_table,
            "cells": config.include_cells,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

    def _tabular_chunking_config(self):
        """Config única del TabularChunker (ingesta y fingerprint de política)."""
        from src.knowledge.tabular.chunker import TabularChunkingConfig
        from src.knowledge.tabular.limits import tabular_limits

        settings = None
        try:
            from src.core.config import get_settings

            settings = get_settings()
        except Exception:  # pragma: no cover - settings siempre disponible
            settings = None
        limits = tabular_limits() if settings is not None else None
        return TabularChunkingConfig(
            row_group_size=limits.row_group_size if limits else 40,
            row_group_overlap=limits.row_group_overlap if limits else 2,
            max_embedding_rows_per_table=limits.max_embedding_rows if limits else 5_000,
            max_group_rows=int(
                getattr(settings, "KNOWLEDGE_TABULAR_MAX_GROUP_ROWS", 20_000)
            ),
            key_columns_for_wide_tables=bool(
                getattr(settings, "KNOWLEDGE_TABULAR_GROUP_KEY_COLUMNS", True)
            ),
            wide_table_columns=int(
                getattr(settings, "KNOWLEDGE_TABULAR_WIDE_TABLE_COLUMNS", 12)
            ),
            max_group_key_columns=int(
                getattr(settings, "KNOWLEDGE_TABULAR_MAX_GROUP_KEY_COLUMNS", 5)
            ),
            max_free_text_chars_in_groups=int(
                getattr(settings, "KNOWLEDGE_TABULAR_MAX_FREE_TEXT_CHARS", 160)
            ),
            include_cells=bool(
                getattr(settings, "KNOWLEDGE_TABULAR_CELL_CHUNKS_ENABLED", False)
            ),
            max_cell_chunks_per_table=int(
                getattr(settings, "KNOWLEDGE_TABULAR_MAX_CELL_CHUNKS", 200)
            ),
        )

    async def _persist_tabular_v2(self, job, source, document, *, change_kind):
        """Persiste el árbol tabular y emite métricas (fail-soft → raise).

        Devuelve el WorkbookDiff (None si el documento no es tabular o no hay
        repositorio tabular configurado).
        """
        workbook = document.tabular
        if workbook is None or self._tabular_v2 is None:
            return None

        import time

        from src.infrastructure.observability.logging_config import get_logger as _get_logger
        from src.infrastructure.observability.metrics import (
            knowledge_tabular_cells_processed,
            knowledge_tabular_parse_errors,
            knowledge_tabular_parse_latency,
            knowledge_tabular_quality_warnings,
            knowledge_tabular_rows_processed,
            knowledge_tabular_rows_upserted,
            knowledge_tabular_schema_changes,
            knowledge_tabular_tables_detected,
        )
        from src.knowledge.tabular.persistence import persist_tabular_workbook

        _logger = _get_logger(__name__)
        started = time.perf_counter()
        organization_id = str(job.organization_id)
        tabular_format = workbook.format.value
        try:
            diff = await persist_tabular_workbook(
                self._tabular_v2,
                workbook,
                knowledge_base_id=job.knowledge_base_id,
                chunking_policy=self._chunking_policy_key(
                    self._tabular_chunking_config()
                ),
            )
        except Exception:
            knowledge_tabular_parse_errors.labels(
                organization_id=organization_id,
                format=tabular_format,
                stage="tabular_persist",
            ).inc()
            raise

        profile = workbook.profile
        knowledge_tabular_tables_detected.labels(
            organization_id=organization_id, format=tabular_format
        ).observe(workbook.table_count)
        if profile is not None:
            knowledge_tabular_cells_processed.labels(
                organization_id=organization_id, format=tabular_format
            ).inc(profile.non_empty_cells)
        knowledge_tabular_parse_latency.labels(
            organization_id=organization_id, format=tabular_format
        ).observe(time.perf_counter() - started)
        for key, value in diff.row_stats.items():
            if value:
                knowledge_tabular_rows_processed.labels(
                    organization_id=organization_id,
                    format=tabular_format,
                    operation=key,
                ).inc(value)
                if key in ("inserted", "updated"):
                    knowledge_tabular_rows_upserted.labels(
                        organization_id=organization_id, format=tabular_format
                    ).inc(value)
        schema_changes = sum(1 for table_diff in diff.table_diffs if table_diff.schema_changed)
        if schema_changes:
            knowledge_tabular_schema_changes.labels(
                organization_id=organization_id, format=tabular_format
            ).inc(schema_changes)
        if workbook.quality is not None:
            for warning in workbook.quality.warnings:
                knowledge_tabular_quality_warnings.labels(
                    organization_id=organization_id,
                    format=tabular_format,
                    code=warning.code,
                ).inc()
        _logger.info(
            "Knowledge Tabular workbook persisted",
            workbook_id=str(workbook.id),
            document_change_kind=change_kind or "unknown",
            change_kind=diff.change_kind.value,
            tables=workbook.table_count,
            rows=workbook.row_count,
            changed_tables=len(diff.changed_table_ids),
            deleted_tables=len(diff.deleted_table_ids),
            rows_inserted=diff.row_stats["inserted"],
            rows_updated=diff.row_stats["updated"],
            rows_deleted=diff.row_stats["deleted"],
        )
        await self._maybe_materialize_managed_db(
            source, workbook, diff, logger=_logger
        )
        return diff

    async def _maybe_materialize_managed_db(self, source, workbook, diff, *, logger) -> None:
        """Materialización opcional en Managed Database (flag + DB existente).

        Best-effort: cualquier fallo es warning; la representación canónica
        (tabular_* en la plataforma) ya quedó persistida. Recuperación: si el
        workbook nunca se materializó (flag recién activado), se materializa
        aunque el diff venga UNCHANGED.
        """
        try:
            from src.core.config import get_settings

            if not get_settings().KNOWLEDGE_TABULAR_MANAGED_DB_ENABLED:
                return
            metadata = dict(diff.metadata or {})
            stored_policy = str(metadata.get("stored_materialization_policy") or "")
            stored_tables = list(metadata.get("stored_materialized_tables") or [])
            # v2: nombre SQL limpio (sin sufijo de rango del detector) y CSV.
            materialization_policy = "v2"
            changed = set(diff.changed_table_ids or [])
            needs = (
                stored_policy != materialization_policy
                or not stored_tables
                or bool(changed)
            )
            if not needs:
                return
            from src.knowledge.tabular.managed_materializer import materialize_tables

            wanted = changed if changed else {table.id for table in workbook.tables()}
            tables = [
                (table, workbook.filename, sheet.name)
                for sheet in workbook.sheets
                for table in sheet.tables
                if table.id in wanted
            ]
            if not tables:
                return
            results = await materialize_tables(
                tables,
                organization_id=workbook.organization_id,
                workspace_id=source.workspace_id,
                source_id=source.id,
            )
            applied = [
                {"name": result.table_name, "rows": result.rows_written}
                for result in results
                if result.status == "applied"
            ]
            status = "applied" if applied else ("skipped" if results else "none")
            detail = next(
                (result.detail for result in results if result.detail), ""
            )
            values: dict = {
                "materialization_status": status,
                "materialized_tables": applied,
                "materialization_detail": detail[:200],
            }
            if applied:
                # Solo se fija la política con materialización efectiva: si la
                # DB no existe todavía, el próximo sync reintenta.
                values["materialization_policy"] = materialization_policy
            if self._tabular_v2 is not None:
                await self._tabular_v2.set_runtime_metadata(
                    workbook.organization_id, workbook.id, values
                )
            logger.info(
                "Knowledge Tabular managed-db materialization",
                results=[result.status for result in results],
                rows=sum(result.rows_written for result in results),
                detail=detail[:120],
            )
        except Exception as exc:  # noqa: BLE001 - nunca rompe la ingesta
            logger.warning(
                "Knowledge Tabular managed-db materialization failed",
                error=str(exc)[:300],
            )

    async def _index_v2_chunks(
        self, job, source, document, *, change_kind: str | None = None,
        acl: dict | None = None,
        tabular_diff: object | None = None,
    ) -> bool | None:
        """Phase C: embebe los chunks V2 (children + parents) y los upserta.

        Dual-write aditivo: misma colección rag_documents y MISMO contrato ACL
        (organization_id en payload + visibility/acl_users/acl_groups del
        record cuando existan). Los chunk_ids usan el namespace V2 para no
        colisionar con los de V1. Fallos aquí son warn (v2_failed); el
        documento estructurado ya quedó persistido en Postgres.

        Los PARENT chunks (document_structure) se indexan para parent
        expansion (contexto de sección) con `v2_parent=true`; los candidates
        de retrieval siguen siendo solo children (`v2_chunk=true`).

        Fingerprinting (§41): contenido sin cambios (change_kind=unchanged) →
        chunks idénticos → se SKIPEA el re-embed y se registra la decisión.

        Knowledge Tabular V2: los documentos Excel/CSV usan TabularChunker y
        un pipeline de índice propio (point keys deterministas + borrado por
        tabla) que permite re-embeder SOLO las tablas cambiadas.
        """
        if document.tabular is not None:
            return await self._index_tabular_chunks(
                job, source, document, tabular_diff=tabular_diff, acl=acl
            )

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
        if not chunks:
            return
        if change_kind == "unchanged":
            logger.info(
                "Knowledge V2 chunks skipped (content unchanged — fingerprint)",
                document_id=str(document.id),
                chunks=len(chunks),
            )
            return

        # F5: limpia puntos V2 previos del documento (re-ingesta con menos
        # chunks, secciones movidas o documento eliminado) antes de reindexar.
        await self._vectors.delete_v2_document(job.organization_id, document.id)

        section_paths = {
            section.id: section.section_path for section in document.sections
        }
        knowledge_base_id = job.knowledge_base_id
        for start in range(0, len(chunks), _EMBED_BATCH):
            batch_chunks = chunks[start : start + _EMBED_BATCH]
            embeddings = await self._embeddings.embed(
                self._embed_texts([c.content for c in batch_chunks])
            )
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]
            if self._usage_tracker is not None:
                try:
                    batch_tokens = sum(c.token_count for c in batch_chunks)
                    costo = await self._embedding_cost(None, batch_tokens)
                    await self._usage_tracker.record_embedding_tokens(
                        job.organization_id,
                        batch_tokens,
                        cost_usd=costo,
                        workspace_id=source.workspace_id,
                        source_id=source.id,
                    )
                    self._observe_ingest("embedding", batch_tokens, costo)
                    await self._record_ingest_usage_event(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        kind="embedding",
                        tokens=batch_tokens,
                        cost_usd=costo,
                        index=start // _EMBED_BATCH,
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
                # RetrievalChunk.metadata = payload["metadata"]; ACL top-level
                # la inyecta upsert_batch desde visibility/acl_*).
                is_parent = chunk.chunk_type is _ChunkType.DOCUMENT_STRUCTURE
                chunk_metadata: dict = {
                    "source_id": str(source.id),
                    "external_id": document.external_id,
                    "content_hash": chunk.content_hash,
                    "chunking_strategy": "document_structure+parent_child",
                    "chunk_type": chunk.chunk_type.value,
                    "chunk_id": str(chunk.id),
                    "section_path": list(section_paths.get(chunk.section_id, ())),
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
                    "v2_chunk": "false" if is_parent else "true",
                    "v2_parent": "true" if is_parent else "false",
                    "v2_doc": "true",
                    **(acl or {}),
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
                job.organization_id, points,
                knowledge_base_id=knowledge_base_id,
                workspace_id=source.workspace_id,
            )

    async def _index_tabular_chunks(
        self,
        job,
        source,
        document,
        *,
        tabular_diff: object | None = None,
        acl: dict | None = None,
    ) -> bool:
        """Representación semántica tabular multinivel (niveles 0-5).

        - Point IDs deterministas (`point_key` del chunker) → upsert idempotente.
        - Borra los puntos de las tablas cambiadas/eliminadas y re-embebe SOLO
          esas tablas (workbook/sheet/schema se re-upsertan siempre, son pocos).
        - Tablas sin cambios: sus puntos quedan intactos (no delete, no embed).
        """
        from src.core.domain.tabular import TabularChangeKind
        from src.knowledge.tabular.chunker import (
            chunk_tabular_workbook,
        )
        from src.knowledge.tabular.ids import point_id_for

        changed_table_ids = None
        if tabular_diff is not None:
            metadata = tabular_diff.metadata or {}
            is_unchanged = (
                tabular_diff.change_kind is TabularChangeKind.UNCHANGED
            )
            needs_index = (not is_unchanged) or bool(
                metadata.get("needs_semantic_index")
            )
            if not needs_index:
                logger.info(
                    "Knowledge Tabular chunks skipped (content unchanged — fingerprint)",
                    document_id=str(document.id),
                )
                return 0
            changed_table_ids = tabular_diff.changed_table_ids
            if is_unchanged:
                # Recuperación: el archivo no cambió pero faltan chunks (p. ej.
                # el worker murió a mitad de indexar). Re-indexa TODAS las
                # tablas; el upsert por point_key es idempotente.
                changed_table_ids = None
                logger.info(
                    "Knowledge Tabular re-indexing (semantic representation missing)",
                    document_id=str(document.id),
                    stored_representations=metadata.get("stored_representations"),
                )
            if metadata.get("policy_changed"):
                # La política de chunking cambió (tamaño de grupos, columnas
                # clave...): los point_keys/serialización anteriores quedan
                # obsoletos → purga total del documento y re-index completo.
                changed_table_ids = None
                try:
                    await self._vectors.delete_v2_document(
                        job.organization_id, document.id
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge Tabular policy purge failed",
                        document_id=str(document.id),
                        error=str(exc)[:300],
                    )
                logger.info(
                    "Knowledge Tabular full re-index (chunking policy changed)",
                    document_id=str(document.id),
                    stored_policy=metadata.get("stored_chunking_policy"),
                )
        if tabular_diff is not None and changed_table_ids is not None:
            scope = list(changed_table_ids) + list(tabular_diff.deleted_table_ids)
            if scope:
                try:
                    await self._vectors.delete_v2_tables(
                        job.organization_id, document.id, scope
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge Tabular point purge failed",
                        document_id=str(document.id),
                        error=str(exc)[:300],
                    )

        config = self._tabular_chunking_config()
        policy = self._chunking_policy_key(config)
        chunks = chunk_tabular_workbook(
            document,
            config=config,
            changed_table_ids=changed_table_ids,
        )
        if not chunks:
            return 0

        knowledge_base_id = job.knowledge_base_id
        embedded = 0
        level_counts: dict[int, int] = {}
        for start in range(0, len(chunks), _EMBED_BATCH):
            batch_chunks = chunks[start : start + _EMBED_BATCH]
            embeddings = await self._embeddings.embed(
                self._embed_texts([c.content for c in batch_chunks])
            )
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]
            if self._usage_tracker is not None:
                try:
                    batch_tokens = sum(c.token_count for c in batch_chunks)
                    costo = await self._embedding_cost(None, batch_tokens)
                    await self._usage_tracker.record_embedding_tokens(
                        job.organization_id,
                        batch_tokens,
                        cost_usd=costo,
                        workspace_id=source.workspace_id,
                        source_id=source.id,
                    )
                    self._observe_ingest("embedding", batch_tokens, costo)
                    await self._record_ingest_usage_event(
                        organization_id=job.organization_id,
                        job_id=job.id,
                        kind="embedding",
                        tokens=batch_tokens,
                        cost_usd=costo,
                        index=start // _EMBED_BATCH,
                        source_id=source.id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Knowledge Tabular usage tracking failed",
                        error=str(exc)[:200],
                    )
            points: list[tuple[UUID, list[float], str, dict | None]] = []
            for chunk, vector in zip(batch_chunks, embeddings):
                metadata = chunk.metadata
                level = int(metadata.get("level") or 0)
                level_counts[level] = level_counts.get(level, 0) + 1
                is_parent = level <= 2
                point_key = metadata.get("point_key")
                point_id = (
                    point_id_for(str(point_key))
                    if point_key
                    else _v2_chunk_id(source.id, document.external_id, chunk.chunk_index)
                )
                chunk_metadata: dict = {
                    **metadata,
                    "chunk_id": str(chunk.id),
                    "chunk_type": chunk.chunk_type.value,
                    "content_hash": chunk.content_hash,
                    "document_id": str(document.id),
                    "knowledge_base_id": (
                        str(knowledge_base_id) if knowledge_base_id else None
                    ),
                    "workspace_id": (
                        str(source.workspace_id) if source.workspace_id else None
                    ),
                    "page_start": None,
                    "page_end": None,
                    "v2_chunk": "false" if is_parent else "true",
                    "v2_parent": "true" if is_parent else "false",
                    "v2_doc": "true",
                    "v2_tabular": "true",
                    **(acl or {}),
                }
                points.append((point_id, list(vector), chunk.content, chunk_metadata))
            await self._vectors.upsert_batch(
                job.organization_id,
                points,
                knowledge_base_id=knowledge_base_id,
                workspace_id=source.workspace_id,
            )
            embedded += len(batch_chunks)

        from src.infrastructure.observability.metrics import (
            knowledge_tabular_chunks_created,
            knowledge_tabular_embeddings_created,
        )

        organization_id = str(job.organization_id)
        tabular_format = document.tabular.format.value if document.tabular else "xlsx"
        for level, count in level_counts.items():
            knowledge_tabular_chunks_created.labels(
                organization_id=organization_id,
                format=tabular_format,
                level=str(level),
            ).inc(count)
        knowledge_tabular_embeddings_created.labels(
            organization_id=organization_id, format=tabular_format
        ).inc(embedded)
        logger.info(
            "Knowledge Tabular chunks indexed",
            document_id=str(document.id),
            chunks=len(chunks),
            embedded=embedded,
            levels={str(level): count for level, count in sorted(level_counts.items())},
        )
        return len(chunks)

    async def _maybe_discover_company(
        self, job, source, document, *, change_kind: str | None = None
    ) -> None:
        """Fase 5B: encola descubrimiento de compañía para el documento.

        Encolar es barato y no bloquea: el motor corre en background. Si el
        hook falla o no está configurado, la ingesta ya terminó bien.
        """
        if self._company_discovery is None:
            return
        hook = getattr(self._company_discovery, "on_document_ingested", None)
        if hook is None:
            return
        try:
            await hook(
                job.organization_id,
                document_id=getattr(document, "id", None),
                source_id=getattr(source, "id", None),
            )
        except Exception as exc:  # noqa: BLE001 - la ingesta nunca se rompe
            logger.warning(
                "Company discovery hook failed",
                error=str(exc)[:200],
                document_id=str(getattr(document, "id", "")),
                change_kind=change_kind or "unknown",
            )

    async def _shadow_summarize(self, document, *, change_kind: str | None = None) -> None:
        """Phase C3 shadow: calcula SectionSummary/DocumentSummary (INFERRED).

        No persiste nada; sirve de calibración (métricas + logs). Si el
        summarizer no está inyectado o falla, el camino V1/V2 sigue intacto.
        Con change_kind=unchanged se SKIPEA (mismo contenido → mismo resumen).
        El uso real (tokens y costo) se registra siempre, y si el costo
        estimado supera el presupuesto se cae al resumen extractivo.
        """
        if self._summarizer is None:
            return
        if change_kind == "unchanged":
            logger.info(
                "Knowledge V2 summaries skipped (content unchanged)",
                document_id=str(document.id),
            )
            return
        from src.knowledge.summarize.service import SummaryUsage

        uso = SummaryUsage()
        permitido = True
        try:
            permitido = await self._summary_within_budget(document)
            output = await self._summarizer.summarize(document, usage=uso, allow_llm=permitido)
            summary = getattr(output, "document_summary", None)
            summary_text = getattr(summary, "summary", "") if summary else ""
            logger.info(
                "Knowledge V2 summary shadow computed",
                document_id=str(document.id),
                summary_chars=len(summary_text[:2000]),
                mode=getattr(output, "mode", "unknown"),
                llm_calls=uso.calls,
                prompt_tokens=uso.prompt_tokens,
                completion_tokens=uso.completion_tokens,
                budget_exceeded=not permitido,
            )
            await self._record_summary_usage(document, uso)
        except Exception as exc:
            logger.warning(
                "Knowledge V2 summary shadow failed",
                document_id=str(document.id),
                error=str(exc)[:500],
            )
            try:
                await self._record_summary_usage(document, uso)
            except Exception:  # noqa: BLE001 — el metering nunca rompe la ingesta
                pass

    async def _summary_within_budget(self, document) -> bool:
        """¿El resumen LLM de este documento entra en el presupuesto por job?"""
        try:
            from src.core.config import get_settings

            presupuesto = float(
                getattr(get_settings(), "KNOWLEDGE_SUMMARY_BUDGET_USD", 0.0) or 0.0
            )
            if presupuesto <= 0:
                return True
            from src.knowledge.structure.base import token_count as _tokens
            from src.platform.billing.pricing import estimate_cost

            modelo = getattr(self._summarizer._config, "model", None)
            texto = "\n".join(
                [getattr(b, "text", "") for b in getattr(document, "blocks", ())]
                + [getattr(t, "text", "") for t in getattr(document, "tables", ())]
            )
            tokens = _tokens(texto)
            costo = float(await estimate_cost(modelo or "", 0, tokens))
            if costo > presupuesto:
                logger.warning(
                    "Knowledge V2 summary skipped (budget)",
                    document_id=str(getattr(document, "id", "")),
                    estimated_cost_usd=round(costo, 6),
                    budget_usd=presupuesto,
                )
                return False
            return True
        except Exception as exc:  # noqa: BLE001 — sin presupuesto, se resume
            logger.warning("Summary budget check failed", error=str(exc)[:150])
            return True

    async def _record_summary_usage(self, document, uso) -> None:
        """Registra tokens/costo del resumen en `knowledge_usage` y `usage_events`."""
        if uso.calls <= 0:
            return
        try:
            from src.platform.billing.pricing import estimate_cost

            modelo = getattr(self._summarizer._config, "model", None) or ""
            costo = float(
                await estimate_cost(
                    modelo or "",
                    uso.prompt_tokens,
                    uso.completion_tokens,
                )
            )
            if self._usage_tracker is not None:
                await self._usage_tracker.record_llm_tokens(
                    document.organization_id,
                    prompt_tokens=uso.prompt_tokens,
                    completion_tokens=uso.completion_tokens,
                    cost_usd=costo,
                    model=modelo or None,
                    purpose="knowledge_summary",
                    workspace_id=getattr(document, "workspace_id", None),
                    source_id=getattr(document, "source_id", None),
                    metadata={
                        "sections_skipped": uso.sections_skipped,
                        "sections_total": uso.sections_total,
                        "calls": uso.calls,
                    },
                )
            from src.infrastructure.observability.metrics import (
                knowledge_ingest_cost_usd,
                knowledge_ingest_tokens_total,
            )

            knowledge_ingest_tokens_total.labels(kind="llm").inc(uso.total_tokens)
            knowledge_ingest_cost_usd.labels(kind="llm").inc(costo)
            await self._record_ingest_usage_event(
                organization_id=document.organization_id,
                job_id=(
                    getattr(document, "id", None)
                    or getattr(document, "source_id", None)
                    or UUID(int=0)
                ),
                kind="llm",
                tokens=uso.total_tokens,
                cost_usd=costo,
                index=0,
                source_id=getattr(document, "source_id", None),
                model=modelo or None,
                prompt_tokens=uso.prompt_tokens,
                completion_tokens=uso.completion_tokens,
            )
        except Exception as exc:  # noqa: BLE001 — el metering nunca rompe la ingesta
            logger.warning("Summary usage record failed", error=str(exc)[:200])


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

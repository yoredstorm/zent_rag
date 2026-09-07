# =============================================================================
# Catalog Discovery Engine — ejecución de jobs de descubrimiento
# =============================================================================
# Mismo patrón que KnowledgeIngestionEngine (jobs durables): pending -> running
# -> completed | partial | failed -> dead (backoff + dead-letter). El estado de
# fase (QUEUED -> SCANNING -> PROFILING -> INFERRING -> WAITING_REVIEW ->
# COMPLETED | PARTIAL | FAILED | CANCELLED) vive en catalog_sources.phase.
# =============================================================================
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from src.catalog.discovery import DiscoveryAdapter, MetadataScanner, content_signature
from src.catalog.enums import EnumDiscovery
from src.catalog.inference import SemanticInference
from src.catalog.relationships import RelationshipDetector
from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorError
from src.connectors.plugin.registry import get_plugin
from src.core.config import get_settings
from src.core.domain.catalog import (
    DiscoveryBudgets,
    DiscoveryPhase,
    ScanBudget,
    ScanType,
)
from src.core.domain.entities import IngestionJobStatus
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    rag_catalog_objects_total,
    rag_discovery_duration_seconds,
    rag_discovery_jobs_total,
)
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)

# Métricas de objetos del catálogo (object_type: table | column | relationship |
# entity | field | enum_value | suggestion).
_OBJECT_TYPE_KEYS = ("table", "column", "relationship", "entity", "field", "enum_value", "suggestion")

DISCOVERY_JOB_PREFIX = "catalog_discovery"


def compute_retry_delay(attempt: int, base_seconds: int = 10, cap_seconds: int = 300) -> int:
    """Backoff exponencial con cap (mismo contrato que el ingestion engine)."""
    return min(base_seconds * (2 ** max(attempt - 1, 0)), cap_seconds)


def _object_counter(organization_id: str, object_type: str) -> None:
    rag_catalog_objects_total.labels(
        organization_id=organization_id, object_type=object_type
    ).inc()


class CatalogDiscoveryEngine:
    """Motor de discovery: escanea metadata y construye el catálogo semántico."""

    def __init__(
        self,
        job_repo: Any,
        connector_repo: Any,
        catalog_store: PostgresCatalogStore | None = None,
        intelligence_store: PostgresIntelligenceStore | None = None,
        secret_store: Any | None = None,
        llm_provider: Any | None = None,
        *,
        backoff_base_seconds: int = 10,
        max_attempts_default: int = 3,
    ) -> None:
        self._jobs = job_repo
        self._connectors = connector_repo
        self._store = catalog_store or PostgresCatalogStore()
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._secrets = secret_store
        self._llm = llm_provider
        self._backoff_base = backoff_base_seconds
        self._max_attempts = max_attempts_default

    # ------------------------------------------------------------------ entry
    async def execute_job(self, job_id: UUID) -> Any:
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
        started = time.perf_counter()
        try:
            await self._run(job)
            duration_ms = (time.perf_counter() - started) * 1000
            rag_discovery_duration_seconds.labels(
                organization_id=str(job.organization_id)
            ).observe(duration_ms / 1000)
        except Exception as exc:
            await self._handle_failure(job_id, job, exc)
        return await self._jobs.get_job(None, job_id)

    async def _handle_failure(self, job_id: UUID, job: Any, exc: Exception) -> None:
        error_text = f"{type(exc).__name__}: {exc}"[:2000]
        try:
            await self._jobs.record_error(job_id, job.attempts, error_text)
        except Exception:  # noqa: BLE001
            pass
        if job.attempts >= (job.max_attempts or self._max_attempts):
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
        # Actualiza fase de la fuente de catálogo a FAILED.
        try:
            cursor = job.cursor_snapshot or {}
            source_id = cursor.get("catalog_source_id")
            if source_id:
                await self._store.update_source(
                    job.organization_id,
                    UUID(source_id),
                    phase=DiscoveryPhase.FAILED.value,
                    scan_error=error_text,
                )
        except Exception:  # noqa: BLE001
            pass
        rag_discovery_jobs_total.labels(
            organization_id=str(job.organization_id),
            engine=job.job_type,
            status=IngestionJobStatus.FAILED.value,
        ).inc()

    # -------------------------------------------------------------------- run
    async def _run(self, job: Any) -> None:
        settings = get_settings()
        scan_started = time.perf_counter()
        cursor = job.cursor_snapshot or {}
        catalog_source_id = cursor.get("catalog_source_id")
        if not catalog_source_id:
            raise ConnectorError("Discovery job missing catalog_source_id in cursor")

        catalog_source = await self._store.get_source(
            job.organization_id, UUID(catalog_source_id)
        )
        if catalog_source is None:
            raise ConnectorError("Catalog source not found for this organization")

        connector = await self._connectors.get_connector(
            job.organization_id, UUID(catalog_source["connector_id"])
        )
        if connector is None:
            raise ConnectorError("Connector not found for this organization")

        secrets: dict = {}
        if self._secrets is not None:
            try:
                secrets = await self._secrets.get(job.organization_id, connector.id) or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("Connector secrets lookup failed", error=str(exc)[:200])

        plugin = get_plugin(connector.type, connector.config_json or {}, secrets)
        await plugin.connect()
        await plugin.validate()

        budgets = DiscoveryBudgets(
            max_tables_per_scan=settings.RAG_CATALOG_MAX_TABLES_PER_SCAN,
            max_columns_per_table=settings.RAG_CATALOG_MAX_COLUMNS_PER_TABLE,
            max_samples=settings.RAG_CATALOG_MAX_SAMPLES,
            max_query_seconds=settings.RAG_CATALOG_MAX_QUERY_SECONDS,
            max_scan_cost=settings.RAG_CATALOG_MAX_SCAN_COST,
            max_parallelism=settings.RAG_CATALOG_MAX_PARALLELISM,
        )
        stored_budgets = catalog_source.get("budgets") or {}
        if stored_budgets:
            for k, v in stored_budgets.items():
                if hasattr(budgets, k) and isinstance(v, (int, float)):
                    setattr(budgets, k, int(v))

        scan_type = cursor.get("scan_type") or ScanType.INITIAL.value
        scan_id = await self._store.create_scan(
            organization_id=job.organization_id,
            source_id=UUID(catalog_source_id),
            scan_type=scan_type,
        )
        scan_budget = ScanBudget(budget=budgets)

        await self._store.update_source(
            job.organization_id,
            UUID(catalog_source_id),
            phase=DiscoveryPhase.SCANNING.value,
            scan_error=None,
        )

        adapter = DiscoveryAdapter(plugin, budgets, connector.id)
        scanner = MetadataScanner(
            self._store,
            budgets=budgets,
            profiling_enabled=settings.RAG_CATALOG_PROFILING_ENABLED,
            drift_check_enabled=settings.RAG_CATALOG_DRIFT_CHECK_ENABLED,
            intelligence_store=self._intel,
        )
        outcome = await scanner.scan(
            organization_id=job.organization_id,
            catalog_source_id=UUID(catalog_source_id),
            adapter=adapter,
            scan_budget=scan_budget,
        )
        _object_counter(str(job.organization_id), "table")

        # PROFILING -> enums (UNDEFINED_ENUM + sugerencias).
        await self._store.update_source(
            job.organization_id,
            UUID(catalog_source_id),
            phase=DiscoveryPhase.PROFILING.value,
        )
        enum_processor = EnumDiscovery(self._store, intelligence_store=self._intel)
        enum_processed = await enum_processor.process(
            organization_id=job.organization_id,
            catalog_source_id=UUID(catalog_source_id),
            enum_columns=outcome.enum_columns,
        )
        for e in enum_processed:
            _object_counter(str(job.organization_id), "enum_value")

        # INFERRING -> relaciones (físicas + candidatas) y semántica.
        await self._store.update_source(
            job.organization_id,
            UUID(catalog_source_id),
            phase=DiscoveryPhase.INFERRING.value,
        )
        deep = await adapter.deep_discover()
        tables_meta = await self._store.list_tables(
            job.organization_id, UUID(catalog_source_id)
        )
        relationship_detector = RelationshipDetector(self._store, budgets=budgets)
        relationships = await relationship_detector.detect(
            organization_id=job.organization_id,
            catalog_source_id=UUID(catalog_source_id),
            deep=deep,
        )
        for r in relationships:
            _object_counter(str(job.organization_id), "relationship")

        inference = SemanticInference(
            self._store,
            llm_provider=self._llm,
            llm_enabled=settings.RAG_CATALOG_INFERENCE_LLM_ENABLED,
        )
        semantic_suggestions = await inference.run(
            organization_id=job.organization_id,
            catalog_source_id=UUID(catalog_source_id),
            deep=deep,
            tables_meta=tables_meta,
        )
        for s in semantic_suggestions:
            _object_counter(str(job.organization_id), "entity")
            _object_counter(str(job.organization_id), "field")
            _object_counter(str(job.organization_id), "suggestion")

        # Fase final + scan record + firma incremental.
        created_suggestions = bool(semantic_suggestions or enum_processed)
        final_phase = (
            DiscoveryPhase.WAITING_REVIEW.value
            if created_suggestions
            else DiscoveryPhase.COMPLETED.value
        )
        if outcome.partial or outcome.errors:
            final_phase = DiscoveryPhase.PARTIAL.value

        scan_status = (
            "partial"
            if (outcome.partial or outcome.errors)
            else ("cancelled" if scan_budget.cancelled else "completed")
        )
        await self._store.update_scan(
            scan_id,
            status=scan_status,
            changes=outcome.changes,
            tables_scanned=outcome.tables_scanned,
            error="; ".join(outcome.errors[:3]) or None,
            duration_ms=(time.perf_counter() - scan_started) * 1000,
        )

        next_scan_at = None
        interval_h = catalog_source.get("scan_interval_hours") or 0
        if interval_h > 0:
            next_scan_at = datetime.now(timezone.utc) + timedelta(hours=interval_h)

        await self._store.update_source(
            job.organization_id,
            UUID(catalog_source_id),
            phase=final_phase,
            last_scan_at=datetime.now(timezone.utc),
            next_scan_at=next_scan_at,
            content_signature=content_signature(deep),
            scan_error=None,
        )

        job_status = IngestionJobStatus.PARTIAL.value if final_phase == DiscoveryPhase.PARTIAL.value else IngestionJobStatus.COMPLETED.value
        await self._jobs.update_job(
            job.id,
            status=job_status,
            progress=100,
            records_processed=outcome.tables_scanned,
            completed_at=datetime.now(timezone.utc),
            error_summary=(
                {"errors": outcome.errors[:5], "partial": True}
                if outcome.errors
                else {}
            ),
        )
        rag_discovery_jobs_total.labels(
            organization_id=str(job.organization_id),
            engine=job.job_type,
            status=job_status,
        ).inc()

        # Invalida el caché de schema del SQL Expert (el esquema pudo cambiar).
        try:
            from src.agents.tools.schema_relevance import SchemaCache

            cache_key = f"sql:schema:{job.organization_id.hex}"
            SchemaCache().invalidate(cache_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema cache invalidation failed", error=str(exc)[:200])


async def start_discovery_scan(
    *,
    job_repo: Any,
    catalog_store: PostgresCatalogStore,
    organization_id: UUID,
    connector_id: UUID,
    kb_source_id: UUID | None = None,
    scan_type: str = ScanType.INITIAL.value,
    scan_interval_hours: int = 0,
) -> dict:
    """Crea el catalog_source (si falta), el job durable y lo encola."""
    from src.knowledge.queue import enqueue_knowledge_job

    catalog_source_id = await catalog_store.upsert_source(
        organization_id=organization_id,
        connector_id=connector_id,
        kb_source_id=kb_source_id,
    )
    source_id = catalog_source_id["id"]
    if scan_interval_hours:
        await catalog_store.update_source(
            organization_id, UUID(source_id), scan_interval_hours=scan_interval_hours
        )

    job = await job_repo.create_job(
        organization_id,
        job_type=f"{DISCOVERY_JOB_PREFIX}:scan",
        source_id=None,
        knowledge_base_id=None,
    )
    await job_repo.update_job(
        job.id,
        cursor_snapshot={
            "catalog_source_id": str(source_id),
            "scan_type": scan_type,
        },
    )
    try:
        await enqueue_knowledge_job(str(job.id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Discovery job enqueue failed", error=str(exc)[:200])
    return {"job_id": str(job.id), "catalog_source_id": str(source_id)}

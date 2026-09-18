# =============================================================================
# Tabular ingestion — auto-ingesta al consultar (lazy) para Excel/CSV
# =============================================================================
# Cuando llega una consulta y la fuente excel/csv aún no tiene representación
# estructurada, se ingesta EN CALIENTE (bounded por tiempo/filas propias:
# RAG_KNOWLEDGE_TABULAR_LAZY_*) y se encola el sync normal para completar la
# representación semántica (embeddings) sin bloquear la respuesta.
#
# Reutiliza el rate limit de lazy ingestion (Redis + fallback en memoria) y las
# métricas rag_lazy_ingestion_*: no se crea infraestructura nueva.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

from src.core.config import get_settings
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.knowledge.storage import resolve_path

logger = get_logger(__name__)

_SOURCE_TYPES = ("excel", "csv")


@dataclass(kw_only=True)
class TabularLazyOutcome:
    """Resultado de un intento de auto-ingesta tabular."""

    triggered: bool = False
    sources_considered: int = 0
    workbooks_persisted: int = 0
    rows_persisted: int = 0
    jobs_enqueued: int = 0
    skipped_reason: str | None = None
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def indexed_anything(self) -> bool:
        return self.workbooks_persisted > 0


class TabularLazyIngestionService:
    """Ingesta on-demand de Excel/CSV pendientes (estructura primero)."""

    def __init__(
        self,
        tabular_repo,
        *,
        enqueue_sync: bool = True,
    ) -> None:
        self._repository = tabular_repo
        self._enqueue_sync = enqueue_sync

    async def ensure_ingested(
        self,
        organization_id: UUID,
        *,
        knowledge_base_id: UUID | None = None,
        source_ids: list[UUID] | None = None,
        max_sources: int | None = None,
    ) -> TabularLazyOutcome:
        """Ingesta (estructura) las fuentes excel/csv pendientes del scope."""
        settings = get_settings()
        started = time.perf_counter()
        outcome = TabularLazyOutcome()
        if not settings.KNOWLEDGE_V2_ENABLED or not settings.KNOWLEDGE_TABULAR_ENABLED:
            outcome.skipped_reason = "tabular_disabled"
            return outcome
        if not settings.KNOWLEDGE_TABULAR_LAZY_ENABLED:
            outcome.skipped_reason = "lazy_disabled"
            return outcome

        # Rate limit compartido con lazy ingestion SQL (abuso de costo).
        from src.platform.usage.lazy_rate_limit import (
            lazy_trigger_allowed,
            record_lazy_trigger,
        )

        if not await lazy_trigger_allowed(organization_id):
            outcome.skipped_reason = "rate_limited"
            return outcome

        pending = await self._pending_sources(
            organization_id,
            knowledge_base_id=knowledge_base_id,
            source_ids=source_ids,
            limit=max_sources or settings.KNOWLEDGE_TABULAR_LAZY_MAX_SOURCES,
        )
        outcome.sources_considered = len(pending)
        if not pending:
            outcome.skipped_reason = "nothing_pending"
            return outcome

        await record_lazy_trigger(organization_id)
        outcome.triggered = True
        from src.infrastructure.observability.metrics import (
            rag_lazy_ingestion_latency,
            rag_lazy_ingestion_rows_indexed,
            rag_lazy_ingestion_triggers_total,
        )

        organization_label = str(organization_id)
        timeout = float(settings.KNOWLEDGE_TABULAR_LAZY_TIMEOUT_SECONDS)
        max_rows = int(settings.KNOWLEDGE_TABULAR_LAZY_MAX_ROWS)
        rag_lazy_ingestion_triggers_total.labels(
            organization_id=organization_label
        ).inc()
        logger.info(
            "Tabular lazy ingestion triggered",
            organization_id=organization_label,
            pending_sources=len(pending),
            max_rows=max_rows,
            timeout_seconds=timeout,
        )

        for source in pending:
            try:
                persisted, rows = await asyncio.wait_for(
                    self._ingest_source(
                        organization_id, source, max_rows=max_rows
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                outcome.errors.append(f"{source['name']}: timeout")
                logger.warning(
                    "Tabular lazy ingestion timed out",
                    source_id=str(source["id"]),
                    timeout_seconds=timeout,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - nunca rompe la respuesta
                outcome.errors.append(f"{source['name']}: {str(exc)[:200]}")
                logger.warning(
                    "Tabular lazy ingestion failed",
                    source_id=str(source["id"]),
                    error=str(exc)[:300],
                )
                continue
            if persisted:
                outcome.workbooks_persisted += 1
                outcome.rows_persisted += rows
                rag_lazy_ingestion_rows_indexed.labels(
                    organization_id=organization_label
                ).inc(rows)
                outcome.jobs_enqueued += await self._enqueue_full_sync(organization_id, source)

        outcome.duration_ms = (time.perf_counter() - started) * 1000
        rag_lazy_ingestion_latency.labels(
            organization_id=organization_label
        ).observe(time.perf_counter() - started)
        logger.info(
            "Tabular lazy ingestion completed",
            organization_id=organization_label,
            workbooks=outcome.workbooks_persisted,
            rows=outcome.rows_persisted,
            jobs=outcome.jobs_enqueued,
            errors=len(outcome.errors),
            duration_ms=round(outcome.duration_ms, 2),
        )
        return outcome

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _pending_sources(
        self,
        organization_id: UUID,
        *,
        knowledge_base_id: UUID | None,
        source_ids: list[UUID] | None,
        limit: int,
    ) -> list[dict]:
        session = await get_async_session()
        try:
            clauses = [
                "s.organization_id = :oid",
                "s.type = ANY(:types)",
                "NOT EXISTS (SELECT 1 FROM tabular_workbooks w "
                "WHERE w.organization_id = s.organization_id AND w.source_id = s.id)",
            ]
            params: dict = {
                "oid": str(organization_id),
                "types": list(_SOURCE_TYPES),
                "limit": max(1, int(limit)),
            }
            if knowledge_base_id is not None:
                clauses.append("s.knowledge_base_id = :kid")
                params["kid"] = str(knowledge_base_id)
            if source_ids:
                clauses.append("s.id = ANY(:sids)")
                params["sids"] = [str(source_id) for source_id in source_ids[:20]]
            result = await session.execute(
                text(
                    "SELECT s.id, s.name, s.type, s.knowledge_base_id, s.config_json "  # noqa: S608 (cláusulas estáticas; valores parametrizados)
                    "FROM kb_sources s "
                    f"WHERE {' AND '.join(clauses)} "
                    "ORDER BY s.created_at DESC LIMIT :limit"
                ),
                params,
            )
            return [
                {
                    "id": row.id,
                    "name": row.name,
                    "type": row.type,
                    "knowledge_base_id": row.knowledge_base_id,
                    "config": row.config_json or {},
                }
                for row in result.fetchall()
            ]
        finally:
            await session.close()

    async def _ingest_source(
        self,
        organization_id: UUID,
        source: dict,
        *,
        max_rows: int,
    ) -> tuple[bool, int]:
        """Parsea + construye + persiste la estructura. Devuelve (persistido, filas)."""
        settings = get_settings()
        object_key = str(source["config"].get("object_key") or "")
        if not object_key:
            return False, 0
        path = resolve_path(organization_id, object_key)
        if not path.exists():
            return False, 0
        size = path.stat().st_size
        if size > int(settings.KNOWLEDGE_TABULAR_MAX_WORKBOOK_BYTES):
            logger.warning(
                "Tabular lazy ingestion skipped: file too large",
                source_id=str(source["id"]),
                size_bytes=size,
            )
            return False, 0

        data = await asyncio.to_thread(path.read_bytes)
        filename = str(source["config"].get("filename") or path.name)
        workbook = await asyncio.to_thread(
            _parse_and_build,
            data,
            filename,
            object_key,
            organization_id,
            source,
            max_rows,
        )
        from src.knowledge.tabular.persistence import persist_tabular_workbook

        diff = await persist_tabular_workbook(
            self._repository,
            workbook,
            knowledge_base_id=source.get("knowledge_base_id"),
        )
        rows = (
            workbook.row_count
            if diff.change_kind.value != "unchanged"
            else 0
        )
        return diff.changed_table_ids != frozenset() or rows > 0, rows

    async def _enqueue_full_sync(self, organization_id: UUID, source: dict) -> int:
        """Encola el sync normal para completar chunks/embeddings (no bloquea)."""
        if not self._enqueue_sync:
            return 0
        try:
            from src.infrastructure.postgres.knowledge_repos import (
                PostgresIngestionJobRepository,
            )
            from src.knowledge.queue import enqueue_knowledge_job

            repository = PostgresIngestionJobRepository()
            job = await repository.create_job(
                organization_id,
                job_type=f"sync_source:{source['type']}",
                source_id=source["id"],
                knowledge_base_id=source.get("knowledge_base_id"),
                max_attempts=3,
            )
            await enqueue_knowledge_job(str(job.id))
            return 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Tabular lazy ingestion could not enqueue sync",
                source_id=str(source["id"]),
                error=str(exc)[:200],
            )
            return 0


def _parse_and_build(
    data: bytes,
    filename: str,
    object_key: str,
    organization_id: UUID,
    source: dict,
    max_rows: int,
):
    """Parseo + construcción síncrona (se ejecuta en thread)."""
    from src.knowledge.tabular.builder import TabularBuildLimits, build_tabular_workbook
    from src.knowledge.tabular.csv_reader import build_csv_workbook_grid
    from src.knowledge.tabular.xlsx_reader import read_xlsx_grid

    extension = Path(object_key or filename).suffix.lower().lstrip(".") or "xlsx"
    limits = TabularBuildLimits(max_rows_per_sheet=max(1, int(max_rows)))
    if extension in ("xlsx", "xlsm"):
        grid = read_xlsx_grid(
            data,
            filename,
            max_rows_per_sheet=limits.max_rows_per_sheet,
            max_columns=limits.max_columns,
            max_cells=limits.max_cells,
        )
    else:
        grid, _dialect = build_csv_workbook_grid(
            data,
            filename,
            max_rows=limits.max_rows_per_sheet,
            max_columns=limits.max_columns,
            max_cells=limits.max_cells,
        )
    source_id = source.get("id")
    return build_tabular_workbook(
        grid,
        organization_id=organization_id,
        external_id=object_key,
        source_id=source_id,
        filename=filename,
        limits=limits,
    )

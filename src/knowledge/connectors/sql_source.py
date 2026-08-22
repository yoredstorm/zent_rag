# =============================================================================
# SQLSourceConnector — port del motor SQL existente (self-contained)
# =============================================================================
# Reutiliza PostgresIngestionService (descubrimiento, FK resolution,
# imágenes, heurísticas verticales como plugins) y lo expone como fuente.
# El motor solo gestiona el ciclo de vida del job (retry/resume/dead letter).
#
# config:
#   tables:  ["schema.tabla", ...]  (vacío = sync_all)
#   exclude_tables: ["tabla", ...]
#   delete_sync: bool — full scan comparando filas vs registry (delete detection)
#   full_refresh: bool — re-indexa todo (borra vectores del source primero)
# =============================================================================
from __future__ import annotations

import time
from datetime import datetime, timezone

from src.core.domain.services import IngestionResult
from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    SourceConnector,
    SyncOutcome,
)


class SQLSourceConnector(SourceConnector):
    source_type = "sql"
    self_contained = True

    def _tables(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for entry in self.config.get("tables") or []:
            schema, _, table = str(entry).partition(".")
            if not table:
                schema, table = "public", schema
            result.append((schema, table))
        return result

    async def _service(self):
        from src.api.deps import (
            get_cache_provider,
            get_embedding_provider,
            get_vector_store,
        )
        from src.connectors.sql.ingestion import PostgresIngestionService

        return PostgresIngestionService(
            get_vector_store(), get_embedding_provider(), get_cache_provider()
        )

    async def validate(self) -> None:
        try:
            sources = await (await self._service()).discover_sources(
                self.source.organization_id
            )
        except Exception as exc:
            raise ConnectorError(f"SQL discovery failed: {exc}") from exc
        configured = self._tables()
        if configured:
            available = {(s.schema_name, s.table_name) for s in sources}
            missing = [f"{s}.{t}" for s, t in configured if (s, t) not in available]
            if missing:
                raise ConnectorError(f"Tables not found: {', '.join(missing)}")

    async def discover(self) -> list[DiscoveredItem]:
        service = await self._service()
        sources = await service.discover_sources(self.source.organization_id)
        return [
            DiscoveredItem(
                external_id=f"{s.schema_name}.{s.table_name}",
                label=f"{s.schema_name}.{s.table_name}",
                extra={"row_count": s.row_count, "is_view": s.is_view},
            )
            for s in sources
        ]

    async def sync(self, cursor: dict | None) -> SyncOutcome:
        service = await self._service()
        organization_id = self.source.organization_id
        start = time.perf_counter()

        full_refresh = bool(self.config.get("full_refresh"))
        delete_sync = bool(self.config.get("delete_sync"))
        exclude = {
            t.strip().lower() for t in (self.config.get("exclude_tables") or [])
        }

        results: list[IngestionResult] = []
        configured = self._tables()
        try:
            if configured:
                for schema, table in configured:
                    if table.lower() in exclude:
                        continue
                    results.append(
                        await service.sync_table(
                            organization_id, schema, table, full_refresh
                        )
                    )
            else:
                result = await service.sync_all(
                    organization_id, full_refresh=full_refresh, job_id=None
                )
                results.append(result)
        except Exception as exc:
            raise ConnectorError(f"SQL sync failed: {exc}") from exc

        records_processed = sum(r.rows_indexed for r in results)
        failed = sum(r.failed_rows for r in results)
        errors = [e for r in results for e in r.errors]

        outcome = SyncOutcome(
            records_processed=records_processed,
            records_failed=failed,
            errors=errors,
            cursor={
                "last_sync_at": datetime.now(timezone.utc).isoformat(),
                "delete_sync": delete_sync,
                "full_refresh": full_refresh,
                "duration_ms": round((time.perf_counter() - start) * 1000, 2),
            },
        )
        return outcome

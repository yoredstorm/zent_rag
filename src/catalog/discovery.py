# =============================================================================
# Discovery Engine — adaptador + scanner seguro de metadata SQL
# =============================================================================
# Source -> Discovery Adapter (plugin) -> Metadata Scanner -> Profiler ->
# Relationship Detector -> Semantic Inference -> Catalog
#
# Seguridad: read-only, incremental (content_hash), presupuestos
# (max_tables/columns/samples/query_seconds/scan_cost/parallelism), cancelable
# y resumible (cursor en ingestion_jobs). NUNCA muestrea columnas sensibles.
# =============================================================================
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.base import ConnectorError, ConnectorPlugin
from src.connectors.plugin.models import DeepSchemaDiscovery, DeepTableProfile
from src.core.domain.catalog import (
    DiscoveryBudgets,
    ScanBudget,
)
from src.core.domain.pii import is_sensitive_column
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


@dataclass
class ScanOutcome:
    """Resultado de un scan de metadata."""

    tables: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    enum_columns: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    partial: bool = False
    tables_scanned: int = 0


def content_signature(deep: DeepSchemaDiscovery) -> str:
    """Firma del contenido para detección incremental de cambios."""
    payload = json.dumps(
        [
            {
                "table": f"{t.schema}.{t.table_name}",
                "is_view": t.is_view,
                "row_count_approx": t.row_count_approx,
                "columns": [
                    {"name": c.name, "data_type": c.data_type, "nullable": c.nullable}
                    for c in t.columns
                ],
            }
            for t in deep.tables
        ],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class DiscoveryAdapter:
    """Adaptador de discovery sobre un ConnectorPlugin (budgets + timeouts)."""

    def __init__(
        self,
        plugin: ConnectorPlugin,
        budgets: DiscoveryBudgets,
        connector_id: UUID,
    ) -> None:
        self._plugin = plugin
        self._budgets = budgets
        self._connector_id = connector_id

    @property
    def plugin(self) -> ConnectorPlugin:
        return self._plugin

    @property
    def budgets(self) -> DiscoveryBudgets:
        return self._budgets

    async def deep_discover(self) -> DeepSchemaDiscovery:
        start = time.perf_counter()
        try:
            return await self._plugin.deep_discover(max_samples=self._budgets.max_samples)
        finally:
            logger.info(
                "Deep discover completed",
                connector_id=str(self._connector_id),
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )


class MetadataScanner:
    """Escanea metadata y persiste el catálogo físico (incremental, seguro)."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        *,
        budgets: DiscoveryBudgets | None = None,
        profiling_enabled: bool = True,
        drift_check_enabled: bool = True,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = store
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._budgets = budgets or DiscoveryBudgets()
        self._profiling_enabled = profiling_enabled
        self._drift_check = drift_check_enabled

    async def scan(
        self,
        *,
        organization_id: UUID,
        catalog_source_id: UUID,
        adapter: DiscoveryAdapter,
        scan_budget: ScanBudget,
    ) -> ScanOutcome:
        """Ejecuta el scan completo; retorna tablas, cambios y enums detectados."""
        outcome = ScanOutcome()
        scan_budget.budget = self._budgets

        try:
            deep = await adapter.deep_discover()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Deep discover failed: {exc}") from exc

        if scan_budget.cancelled:
            outcome.partial = True
            return outcome

        active_table_ids: list[UUID] = []
        for table in deep.tables:
            if scan_budget.cancelled or not scan_budget.add_query():
                outcome.partial = True
                break
            table_id, is_new = await self._store.upsert_table(
                organization_id=organization_id,
                source_id=catalog_source_id,
                schema_name=table.schema,
                table_name=table.table_name,
                is_view=table.is_view,
                row_count_approx=table.row_count_approx,
                table_comment=table.table_comment,
                content_hash=_table_hash(table),
            )
            active_table_ids.append(table_id)
            scan_budget.tables_scanned += 1
            outcome.tables_scanned += 1

            if is_new:
                outcome.changes.append(
                    {
                        "type": "table_added",
                        "object": f"{table.schema}.{table.table_name}",
                    }
                )

            existing_columns = {
                c["column_name"]: c for c in await self._store.list_columns(
                    organization_id, table_id
                )
            }
            seen_columns: set[str] = set()
            for col in table.columns:
                seen_columns.add(col.name)
                prev = existing_columns.get(col.name)
                if prev and prev.get("data_type") != col.data_type:
                    outcome.changes.append(
                        {
                            "type": "type_changed",
                            "object": f"{table.schema}.{table.table_name}.{col.name}",
                            "detail": {
                                "from": prev.get("data_type"),
                                "to": col.data_type,
                            },
                        }
                    )
                await self._store.upsert_column(
                    organization_id=organization_id,
                    table_id=table_id,
                    column_name=col.name,
                    ordinal_position=0,
                    data_type=col.data_type,
                    nullable=col.nullable,
                    is_primary_key=col.is_primary_key,
                    column_comment=col.column_comment,
                    null_ratio=col.null_ratio,
                    cardinality_approx=col.cardinality,
                    pii_flags=col.pii_flags,
                    is_sensitive=col.sensitive,
                    sample_disabled=col.sample_disabled,
                )
            for name in set(existing_columns) - seen_columns:
                outcome.changes.append(
                    {
                        "type": "column_removed",
                        "object": f"{table.schema}.{table.table_name}.{name}",
                    }
                )

            # Profiling: detección de columnas categóricas (enums) si aplica.
            if self._profiling_enabled and not scan_budget.cancelled:
                enum_info = await self._detect_enum_column(
                    organization_id=organization_id,
                    table_id=table_id,
                    table=table,
                    adapter=adapter,
                    scan_budget=scan_budget,
                )
                if enum_info:
                    outcome.enum_columns.append(enum_info)

        # Drift: tablas activas no vistas en este scan -> removidas.
        if self._drift_check and not scan_budget.cancelled:
            removed = await self._store.mark_tables_removed(
                organization_id, catalog_source_id, active_table_ids
            )
            for r in removed:
                outcome.changes.append(
                    {"type": "table_removed", "object": r["qualified_name"]}
                )

        return outcome

    async def _detect_enum_column(
        self,
        *,
        organization_id: UUID,
        table_id: UUID,
        table: DeepTableProfile,
        adapter: DiscoveryAdapter,
        scan_budget: ScanBudget,
    ) -> dict | None:
        """Detecta columnas categóricas (cardinalidad pequeña) y muestrea valores.

        Solo para columnas NO sensibles, con presupuesto de queries.
        """
        candidates = [
            c
            for c in table.columns
            if not c.sample_disabled
            and not is_sensitive_column(c.name)
            and (c.cardinality is None or c.cardinality <= 50)
            and c.data_type.lower() in ("character varying", "varchar", "text", "char", "bpchar", "enum")
        ]
        if not candidates or not scan_budget.add_query():
            return None
        sampled: dict[str, list[str]] = {}
        for col in candidates:
            if scan_budget.cancelled or not scan_budget.add_query():
                break
            try:
                values = await adapter.plugin.sample_distinct_values(
                    table.schema, table.table_name, col.name,
                    max_samples=adapter.budgets.max_samples,
                )
                scan_budget.samples_taken += len(values)
                if values:
                    sampled[col.name] = values
            except Exception as exc:  # noqa: BLE001
                logger.warning("Enum sampling failed", error=str(exc)[:200])
        if not sampled:
            return None
        return {
            "schema": table.schema,
            "table": table.table_name,
            "table_id": str(table_id),
            "samples": sampled,
        }


def _table_hash(table: DeepTableProfile) -> str:
    payload = json.dumps(
        {
            "name": f"{table.schema}.{table.table_name}",
            "is_view": table.is_view,
            "row_count": table.row_count_approx,
            "columns": [
                {
                    "name": c.name,
                    "type": c.data_type,
                    "nullable": c.nullable,
                    "comment": c.column_comment,
                }
                for c in table.columns
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

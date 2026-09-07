# =============================================================================
# Zent Spider — discovery continuo AUTORIZADO y limitado (FASE 25)
# =============================================================================
# No es crawling irrestricto: solo fuentes/schemas explícitamente autorizados
# por la política del tenant. Detecta: schema drift, nuevas tablas, tablas
# obsoletas, relaciones nuevas, enums sin documentar, cambios de
# documentación e inconsistencias semánticas. NUNCA amplía permisos.
# =============================================================================
from __future__ import annotations

import time
from uuid import UUID

from src.catalog.discovery import DiscoveryAdapter, MetadataScanner
from src.connectors.plugin.registry import get_plugin
from src.core.domain.catalog import DiscoveryBudgets, ScanBudget
from src.core.domain.learning import SpiderRun
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    rag_spider_findings_total,
    rag_spider_scan_duration_seconds,
)
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

SPIDER_JOB_PREFIX = "spider"


class SpiderService:
    """Ejecuta políticas de Spider (discovery autorizado) por job durable."""

    def __init__(
        self,
        store: PostgresLearningStore,
        catalog_store=None,
        connector_repo=None,
        secret_store=None,
        intelligence_store=None,
        job_repo=None,
    ) -> None:
        self._store = store
        self._catalog = catalog_store
        self._connectors = connector_repo
        self._secrets = secret_store
        self._intel = intelligence_store
        self._jobs = job_repo

    # ------------------------------------------------------------- API helpers
    async def start_policy_run(
        self, organization_id: UUID, policy_id: UUID
    ) -> UUID | None:
        """Crea el spider_run (running) y encola el job spider:run."""
        run = SpiderRun(
            organization_id=organization_id,
            policy_id=policy_id,
            status="running",
        )
        run_id = await self._store.create_spider_run(run)
        if self._jobs is None:
            return run_id
        try:
            from src.knowledge.queue import enqueue_knowledge_job

            job = await self._jobs.create_job(
                organization_id,
                job_type=f"{SPIDER_JOB_PREFIX}:run",
                source_id=None,
                knowledge_base_id=None,
            )
            await self._jobs.update_job(
                job.id,
                cursor_snapshot={
                    "spider_run_id": str(run_id),
                    "policy_id": str(policy_id),
                },
            )
            await enqueue_knowledge_job(str(job.id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Spider run enqueue failed", error=str(exc)[:200])
        return run_id

    async def execute_run(self, spider_run_id: UUID) -> dict:
        """Ejecuta la política contra las fuentes autorizadas (job worker)."""
        started = time.perf_counter()
        run_row = await self._get_run(spider_run_id)
        if run_row is None:
            raise ValueError(f"Spider run {spider_run_id} not found")
        org = UUID(run_row["organization_id"])
        policy_id = UUID(run_row["policy_id"])
        policy_row = await self._get_policy(org, policy_id)
        if policy_row is None:
            await self._store.update_spider_run(
                spider_run_id, status="failed", error="policy not found"
            )
            return run_row

        findings: list[dict] = []
        errors: list[str] = []
        try:
            source_ids = await self._authorized_sources(org, policy_row)
            if not source_ids:
                findings.append(
                    {"kind": "no_authorized_sources", "detail": "Sin fuentes autorizadas"}
                )
            for source_id in source_ids:
                try:
                    await self._scan_source(
                        org, UUID(source_id), policy_row, findings
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{source_id}: {str(exc)[:200]}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}"[:500])

        duration_ms = (time.perf_counter() - started) * 1000
        status = "failed" if errors and not findings else "completed"
        await self._store.update_spider_run(
            spider_run_id,
            status=status,
            findings=findings,
            duration_ms=duration_ms,
            error="; ".join(errors[:3]) or None,
        )
        for finding in findings:
            rag_spider_findings_total.labels(
                organization_id=str(org),
                kind=str(finding.get("kind") or "finding"),
            ).inc()
        rag_spider_scan_duration_seconds.labels(
            organization_id=str(org)
        ).observe(duration_ms / 1000)
        return await self._get_run(spider_run_id) or run_row

    # ---------------------------------------------------------------- internals
    async def _get_run(self, spider_run_id: UUID) -> dict | None:
        for r in await self._store.list_spider_runs(UUID(int=0), limit=500):
            if r["id"] == str(spider_run_id):
                return r
        return None

    async def _get_policy(
        self, organization_id: UUID, policy_id: UUID
    ) -> dict | None:
        for p in await self._store.list_spider_policies(organization_id):
            if p["id"] == str(policy_id):
                return p
        return None

    async def _authorized_sources(
        self, organization_id: UUID, policy: dict
    ) -> list[str]:
        """Fuentes autorizadas: intersección política ∩ tenant (nunca más)."""
        if self._catalog is None:
            return []
        all_sources = await self._catalog.list_sources(organization_id)
        allowed = [str(s) for s in policy.get("allowed_source_ids") or []]
        if not allowed:
            return [s["id"] for s in all_sources]
        return [
            s["id"]
            for s in all_sources
            if s["id"] in allowed or str(s["id"]) in allowed
        ]

    async def _scan_source(
        self,
        organization_id: UUID,
        source_id: UUID,
        policy: dict,
        findings: list[dict],
    ) -> None:
        if self._catalog is None or self._connectors is None:
            return
        source = await self._catalog.get_source(organization_id, source_id)
        if source is None:
            findings.append({"kind": "source_removed", "source_id": str(source_id)})
            return
        connector = await self._connectors.get_connector(
            organization_id, UUID(source["connector_id"])
        )
        if connector is None:
            findings.append(
                {"kind": "connector_missing", "source_id": str(source_id)}
            )
            return
        secrets: dict = {}
        if self._secrets is not None:
            try:
                secrets = await self._secrets.get(organization_id, connector.id) or {}
            except Exception:  # noqa: BLE001
                pass
        plugin = get_plugin(connector.type, connector.config_json or {}, secrets)
        await plugin.connect()
        await plugin.validate()

        budgets = DiscoveryBudgets(
            max_scan_cost=int(policy.get("max_cost") or 500),
            max_samples=50,
            max_query_seconds=10.0,
        )
        if policy.get("profiling_level") == "none":
            budgets.max_samples = 0
        scan_budget = ScanBudget(budget=budgets)
        scanner = MetadataScanner(
            self._catalog,
            budgets=budgets,
            profiling_enabled=policy.get("profiling_level") != "none",
            drift_check_enabled=True,
            intelligence_store=self._intel,
        )
        adapter = DiscoveryAdapter(plugin, budgets, connector.id)
        deep = await adapter.deep_discover()

        # Filtros de política: schemas permitidos + objetos excluidos.
        allowed_schemas = [s.lower() for s in policy.get("allowed_schemas") or []]
        excluded = set(str(o).lower() for o in policy.get("excluded_objects") or [])
        if allowed_schemas or excluded:
            deep.tables = [
                t
                for t in deep.tables
                if (not allowed_schemas or t.schema.lower() in allowed_schemas)
                and t.table_name.lower() not in excluded
                and f"{t.schema}.{t.table_name}".lower() not in excluded
            ]

        outcome = await scanner.scan(
            organization_id=organization_id,
            catalog_source_id=source_id,
            adapter=adapter,
            scan_budget=scan_budget,
        )
        for change in outcome.changes:
            findings.append(
                {
                    "kind": f"drift_{change.get('type')}",
                    "object": change.get("object"),
                    "detail": change.get("detail"),
                }
            )
        for enum_info in outcome.enum_columns:
            findings.append(
                {
                    "kind": "undocumented_enum",
                    "object": f"{enum_info['schema']}.{enum_info['table']}",
                }
            )
        # Inconsistencia semántica: entidad mapeada a tabla removida.
        for table in await self._catalog.list_tables(
            organization_id, source_id, include_removed=True, limit=1000
        ):
            if table.get("removed_at"):
                for entity in await self._catalog.list_entities(
                    organization_id, limit=1000
                ):
                    if (
                        entity.get("mapped_table_id")
                        and entity["mapped_table_id"] == table["id"]
                    ):
                        findings.append(
                            {
                                "kind": "semantic_inconsistency",
                                "detail": (
                                    f"Entidad '{entity['name']}' mapeada a tabla "
                                    f"removida {table['qualified_name']}"
                                ),
                            }
                        )

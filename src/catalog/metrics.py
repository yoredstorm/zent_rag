# =============================================================================
# Business Metrics — métricas gobernadas (nunca se ejecutan fórmulas sin validar)
# =============================================================================
# definition, formula, semantic_dependencies, physical_mappings, filters,
# time/currency semantics, owner, status, version. Al aprobar, la métrica se
# sincroniza (idempotente) a business_definitions para que el Answerability
# Gate la reconozca (data_type='metric', expression=formula).
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid4

from src.catalog.lineage import LineageService
from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import CatalogMetric
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


class MetricsService:
    """Gobernanza de business metrics."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = store
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._lineage = LineageService(store)

    async def list(
        self,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        return await self._store.list_metrics(
            organization_id, status=status, limit=limit, offset=offset
        )

    async def get(self, organization_id: UUID, metric_id: UUID) -> dict | None:
        return await self._store.get_metric(organization_id, metric_id)

    async def upsert(
        self,
        *,
        organization_id: UUID,
        metric_key: str,
        name: str,
        definition: str,
        formula: str | None = None,
        semantic_dependencies: list[str] | None = None,
        physical_mappings: list[dict] | None = None,
        filters: list[dict] | None = None,
        time_semantics: str | None = None,
        currency_semantics: str | None = None,
        owner: str | None = None,
        status: str = "draft",
        created_by: UUID | None = None,
        effective_from=None,
        effective_to=None,
    ) -> dict:
        metric = CatalogMetric(
            id=uuid4(),
            organization_id=organization_id,
            metric_key=metric_key.strip().lower(),
            name=name,
            definition=definition,
            formula=formula,
            semantic_dependencies=semantic_dependencies or [],
            physical_mappings=physical_mappings or [],
            filters=filters or [],
            time_semantics=time_semantics,
            currency_semantics=currency_semantics,
            owner=owner,
            status=status,
            version=1,
            created_by=created_by,
            approved_by=created_by if status == "approved" else None,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        await self._store.upsert_metric(metric)
        if status == "approved":
            await self._sync_to_definitions(metric)
        return await self._store.get_metric(organization_id, metric.id) or {}

    async def approve(
        self, organization_id: UUID, metric_id: UUID, approved_by: UUID | None = None
    ) -> dict | None:
        metric = await self._store.get_metric(organization_id, metric_id)
        if metric is None:
            return None
        updated = CatalogMetric(
            id=UUID(metric["id"]),
            organization_id=organization_id,
            metric_key=metric["metric_key"],
            name=metric["name"],
            definition=metric["definition"],
            formula=metric["formula"],
            semantic_dependencies=metric["semantic_dependencies"],
            physical_mappings=metric["physical_mappings"],
            filters=metric["filters"],
            time_semantics=metric["time_semantics"],
            currency_semantics=metric["currency_semantics"],
            owner=metric["owner"],
            status="approved",
            version=metric["version"],
            created_by=UUID(metric["created_by"]) if metric.get("created_by") else None,
            approved_by=approved_by,
            effective_from=metric["effective_from"],
            effective_to=metric["effective_to"],
        )
        await self._store.upsert_metric(updated)
        await self._sync_to_definitions(updated)
        return await self._store.get_metric(organization_id, metric_id)

    async def _sync_to_definitions(self, metric: CatalogMetric) -> None:
        """Sincroniza la métrica aprobada a business_definitions (idempotente)."""
        saved = await self._intel.upsert_definition(
            organization_id=metric.organization_id,
            concept=metric.metric_key,
            definition=metric.definition,
            expression=metric.formula,
            data_type="metric",
            status="approved",
            created_by=metric.created_by,
            synonyms=[],
            owner=metric.owner,
            version=metric.version,
            effective_from=metric.effective_from,
            effective_to=metric.effective_to,
            approved_by=metric.approved_by,
            provenance="APPROVED",
        )
        metric.definition_id = saved.id
        await self._store.upsert_metric(metric)
        await self._lineage.record_metric_definition(
            organization_id=metric.organization_id,
            metric_id=metric.id,
            definition_id=saved.id,
        )
        for mapping in metric.physical_mappings:
            table = str(mapping.get("table") or "")
            column = str(mapping.get("column") or "")
            if table and column:
                await self._lineage.add_edge(
                    organization_id=metric.organization_id,
                    upstream_type="business_metric",
                    upstream_id=metric.id,
                    downstream_type="physical_column",
                    downstream_id=f"{table}.{column}",
                    relation="MAPS_TO",
                )

# =============================================================================
# Lineage — aristas estructuradas (Lineage + Enterprise Context Graph)
# =============================================================================
# Registra y lee aristas: Business Entity USES Metric, Metric DEPENDS_ON Field,
# Field MAPS_TO Column, Glossary DEFINES Concept, Source IS_AUTHORITY_FOR
# Concept. Modelado en PostgreSQL (sin graph DB nueva).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import LineageEdge, LineageRelation
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


class LineageService:
    """Servicio de lineage/contexto del catálogo."""

    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store

    async def add_edge(
        self,
        *,
        organization_id: UUID,
        upstream_type: str,
        upstream_id: str,
        downstream_type: str,
        downstream_id: str,
        relation: LineageRelation,
        metadata: dict | None = None,
    ) -> None:
        edge = LineageEdge(
            organization_id=organization_id,
            upstream_type=upstream_type,
            upstream_id=str(upstream_id),
            downstream_type=downstream_type,
            downstream_id=str(downstream_id),
            relation=relation,
            metadata=metadata or {},
        )
        await self._store.add_lineage_edge(edge)

    async def list(
        self,
        organization_id: UUID,
        *,
        object_type: str | None = None,
        object_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        return await self._store.list_lineage(
            organization_id, object_type=object_type, object_id=object_id, limit=limit
        )

    async def record_entity_mapping(
        self,
        *,
        organization_id: UUID,
        entity_id: UUID,
        table_id: UUID,
    ) -> None:
        await self.add_edge(
            organization_id=organization_id,
            upstream_type="business_entity",
            upstream_id=entity_id,
            downstream_type="physical_table",
            downstream_id=table_id,
            relation=LineageRelation.MAPS_TO,
        )

    async def record_field_mapping(
        self,
        *,
        organization_id: UUID,
        field_id: UUID,
        column_id: UUID,
    ) -> None:
        await self.add_edge(
            organization_id=organization_id,
            upstream_type="business_field",
            upstream_id=field_id,
            downstream_type="physical_column",
            downstream_id=column_id,
            relation=LineageRelation.MAPS_TO,
        )

    async def record_metric_definition(
        self,
        *,
        organization_id: UUID,
        metric_id: UUID,
        definition_id: UUID,
    ) -> None:
        await self.add_edge(
            organization_id=organization_id,
            upstream_type="business_metric",
            upstream_id=metric_id,
            downstream_type="glossary_term",
            downstream_id=definition_id,
            relation=LineageRelation.DEFINES,
        )

    async def record_authority(
        self,
        *,
        organization_id: UUID,
        concept: str,
        source_name: str,
    ) -> None:
        await self.add_edge(
            organization_id=organization_id,
            upstream_type="source",
            upstream_id=source_name,
            downstream_type="business_concept",
            downstream_id=concept,
            relation=LineageRelation.IS_AUTHORITY_FOR,
        )

# =============================================================================
# Context Readiness — readiness por fuente con composición explicable
# =============================================================================
# Nunca un % único sin composición: schema_coverage, relationship_coverage,
# description_coverage, semantic_mapping_coverage, metric_coverage,
# glossary_coverage, freshness, data_quality, unknown_code_count,
# pending_review_count.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import ReadinessReport
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)

_FRESH_DAYS = 7
_WEIGHTS = {
    "schema_coverage": 0.15,
    "relationship_coverage": 0.15,
    "description_coverage": 0.10,
    "semantic_mapping_coverage": 0.15,
    "metric_coverage": 0.10,
    "glossary_coverage": 0.15,
    "freshness": 0.10,
    "data_quality": 0.10,
}


class ReadinessService:
    """Calcula Context Readiness por fuente (composición siempre disponible)."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    async def for_source(
        self, organization_id: UUID, source_id: UUID
    ) -> ReadinessReport:
        report = ReadinessReport(
            organization_id=organization_id, source_id=source_id
        )
        tables = await self._store.list_tables(organization_id, source_id)
        if not tables:
            return report

        # Schema coverage: tablas con columnas registradas.
        tables_with_columns = 0
        total_columns = 0
        commented_tables = 0
        commented_columns = 0
        null_ratios: list[float] = []
        for t in tables:
            cols = await self._store.list_columns(organization_id, UUID(t["id"]))
            if cols:
                tables_with_columns += 1
            total_columns += len(cols)
            if t.get("table_comment"):
                commented_tables += 1
            commented_columns += sum(1 for c in cols if c.get("column_comment"))
            null_ratios.extend(
                c["null_ratio"]
                for c in cols
                if c.get("null_ratio") is not None
            )
        report.schema_coverage = round(
            tables_with_columns / max(len(tables), 1) * 100, 2
        )
        report.description_coverage = round(
            (commented_tables / max(len(tables), 1)) * 50
            + (0 if total_columns == 0 else commented_columns / total_columns * 50),
            2,
        )

        # Relationship coverage: tablas con relación confirmada / total activas.
        relationships = await self._store.list_relationships(
            organization_id, source_id, limit=1000
        )
        confirmed_tables = {
            r["from_table_id"]
            for r in relationships
            if r["status"] == "confirmed"
        }
        report.relationship_coverage = round(
            len(confirmed_tables) / max(len(tables), 1) * 100, 2
        )

        # Semantic mapping coverage: columnas mapeadas a campos aprobados.
        mapped_columns = 0
        for entity in await self._store.list_entities(organization_id, limit=1000):
            for f in await self._store.list_fields(
                organization_id, UUID(entity["id"])
            ):
                if f.get("mapped_column_id") and f.get("status") == "approved":
                    mapped_columns += 1
        report.semantic_mapping_coverage = round(
            mapped_columns / max(total_columns, 1) * 100, 2
        )

        # Métricas y glosario (saturados a 100).
        metrics = await self._store.list_metrics(organization_id, limit=1000)
        approved_metrics = sum(1 for m in metrics if m["status"] == "approved")
        report.metric_coverage = round(
            min(approved_metrics / max(len(metrics), 1) * 100, 100.0), 2
        ) if metrics else 0.0

        definitions = await self._intel.list_definitions(organization_id)
        approved_defs = sum(1 for d in definitions if d.status == "approved")
        report.glossary_coverage = round(
            min(approved_defs / max(len(definitions), 1) * 100, 100.0), 2
        ) if definitions else 0.0

        # Freshness: último scan hace <= 7 días.
        source = await self._store.get_source(organization_id, source_id)
        last_scan = source.get("last_scan_at") if source else None
        if last_scan:
            try:
                last = datetime.fromisoformat(last_scan)
                days = (datetime.now(timezone.utc) - last).total_seconds() / 86400
                report.freshness = round(max(0.0, 1.0 - days / _FRESH_DAYS) * 100, 2)
            except ValueError:
                report.freshness = 0.0
        else:
            report.freshness = 0.0

        # Data quality: 1 - null_ratio promedio (0..1) sobre columnas perfiladas.
        if null_ratios:
            report.data_quality = round(
                (1.0 - sum(null_ratios) / len(null_ratios)) * 100, 2
            )
        else:
            report.data_quality = 50.0  # sin perfiles: desconocido

        # Contadores de gaps/revisión.
        enum_columns: list[str] = []
        for t in tables:
            for c in await self._store.list_columns(organization_id, UUID(t["id"])):
                if c.get("pii_flags") or c.get("is_sensitive"):
                    continue
                values = await self._store.list_enum_values(
                    organization_id, UUID(c["id"])
                )
                if values and not any(
                    v["status"] == "approved" and v.get("documented_meaning")
                    for v in values
                ):
                    enum_columns.append(c["id"])
        report.unknown_code_count = len(enum_columns)

        suggestions = await self._store.list_suggestions(
            organization_id, status="pending", limit=500
        )
        report.pending_review_count = len(suggestions)

        # Overall ponderado (los counts no puntúan).
        dimensions = [
            report.schema_coverage,
            report.relationship_coverage,
            report.description_coverage,
            report.semantic_mapping_coverage,
            report.metric_coverage,
            report.glossary_coverage,
            report.freshness,
            report.data_quality,
        ]
        total_weight = sum(_WEIGHTS.values())
        report.overall = round(
            sum(d * w for d, w in zip(dimensions, _WEIGHTS.values())) / total_weight,
            2,
        )
        return report

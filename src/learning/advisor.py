# =============================================================================
# Context Advisor — recomendaciones accionables basadas en evidencia
# =============================================================================
# No dice solo "missing context": muestra qué hay disponible (catálogo real),
# qué falta y qué hacer. Determinista sobre datos del catálogo + glosario.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.learning import ContextGapType
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore
from src.learning.store import PostgresLearningStore

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9_]+")

_MISSING_KEYWORDS = {
    ContextGapType.MISSING_TABLE: ["tabla", "table", "source", "fuente", "data", "datos"],
    ContextGapType.MISSING_FIELD: ["campo", "field", "columna", "column", "dato", "value"],
}

_AVAILABLE_HINTS = {
    ContextGapType.MISSING_METRIC: ("sales", "venta", "revenue", "ingreso", "refund", "devolu"),
    ContextGapType.MISSING_BUSINESS_TERM: ("status", "state", "estado", "code", "cd"),
}

_RECOMMENDATIONS = {
    ContextGapType.MISSING_SOURCE: "Conectar la fuente de datos requerida o reindexar la knowledge base.",
    ContextGapType.MISSING_TABLE: "Conectar la fuente que contiene los datos o mapear una columna equivalente.",
    ContextGapType.MISSING_FIELD: "Mapear el campo equivalente en el catálogo semántico (Business Field).",
    ContextGapType.MISSING_RELATIONSHIP: "Confirmar la relación candidata en /catalog/relationships.",
    ContextGapType.MISSING_BUSINESS_TERM: "Agregar o validar la definición en Business Glossary.",
    ContextGapType.MISSING_METRIC: "Crear y aprobar la métrica en /catalog/metrics.",
    ContextGapType.UNDEFINED_ENUM: "Agregar o validar el significado de estos códigos en Business Glossary.",
    ContextGapType.AMBIGUOUS_TERM: "Precisar el término en el glosario o pedir aclaración al usuario.",
    ContextGapType.STALE_SOURCE: "Ejecutar un rescan del Discovery Engine / verificar la conectividad de la fuente.",
    ContextGapType.LOW_DATA_QUALITY: "Revisar la calidad de la fuente: frescura, cobertura y perfiles.",
    ContextGapType.SOURCE_CONFLICT: "Configurar una fuente autoritativa para la métrica en /catalog/authority.",
    ContextGapType.PERMISSION_LIMITATION: "Revisar permisos/blocklists del rol para esta consulta.",
    ContextGapType.UNSUPPORTED_OPERATION: "La operación no está soportada por las fuentes actuales.",
}

_GENERIC_RECOMMENDATION = (
    "Revisar la evidencia y el catálogo semántico de la organización."
)


def _gap_type_or_none(value: str) -> ContextGapType | None:
    try:
        return ContextGapType(value) if value else None
    except ValueError:
        return None


class ContextAdvisor:
    """Genera recomendaciones accionables a partir de gaps/abstenciones."""

    def __init__(
        self,
        catalog_store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
        learning_store: PostgresLearningStore | None = None,
    ) -> None:
        self._catalog = catalog_store
        self._intel = intelligence_store or PostgresIntelligenceStore()
        self._learning = learning_store or PostgresLearningStore()

    async def advise(
        self,
        organization_id: UUID,
        question: str,
        gap: dict | None = None,
    ) -> dict:
        """Devuelve disponible / no-disponible / recomendación / impacto."""
        gap = gap or {}
        gap_type = gap.get("gap_type") or ""
        gap_kind = _gap_type_or_none(gap_type)
        concept = gap.get("concept") or ""
        tokens = self._tokens(question)

        available: list[str] = []
        missing: list[str] = []

        # 1) Glosario: qué definiciones existen/ faltan para el concepto.
        definitions = await self._intel.list_definitions(organization_id)
        defined_concepts = {d.concept for d in definitions if d.status == "approved"}
        if gap_kind in (
            ContextGapType.MISSING_BUSINESS_TERM,
            ContextGapType.MISSING_METRIC,
        ) or concept:
            if concept and concept not in defined_concepts:
                missing.append(f"Definición aprobada de {concept}")
            for d in definitions:
                if d.status == "approved" and (
                    any(t in d.concept for t in tokens)
                    or any(s in concept for s in d.synonyms)
                    or any(s in d.synonyms for s in tokens)
                ):
                    available.append(f"Glosario: {d.concept}")

        # 2) Catálogo físico: columnas que matchean tokens / hints.
        hints = (
            _AVAILABLE_HINTS.get(gap_kind) if gap_kind is not None else ()
        )
        columns_found: list[str] = []
        for source in await self._catalog.list_sources(organization_id):
            for table in await self._catalog.list_tables(organization_id, UUID(source["id"]), limit=1000):
                cols = await self._catalog.list_columns(organization_id, UUID(table["id"]))
                for col in cols:
                    name = col["column_name"].lower()
                    if col.get("is_sensitive"):
                        continue
                    if any(t in name for t in tokens) or any(h in name for h in hints):
                        columns_found.append(
                            f"{table['qualified_name']}.{col['column_name']}"
                        )
        available.extend(columns_found[:6])

        # 3) Enums sin documentar (UNDEFINED_ENUM).
        if gap_kind == ContextGapType.UNDEFINED_ENUM:
            for source in await self._catalog.list_sources(organization_id):
                for table in await self._catalog.list_tables(organization_id, UUID(source["id"]), limit=1000):
                    for col in await self._catalog.list_columns(organization_id, UUID(table["id"])):
                        values = await self._catalog.list_enum_values(organization_id, UUID(col["id"]))
                        undocumented = [
                            v["value"] for v in values
                            if v["status"] != "approved" or not v.get("documented_meaning")
                        ]
                        if undocumented:
                            missing.append(
                                f"Significado de {table['qualified_name']}.{col['column_name']}: "
                                f"{', '.join(undocumented[:8])}"
                            )

        # 4) Keywords faltantes para tipos de dato (COGS/cost).
        for kw in _MISSING_KEYWORDS.get(gap_kind, ()) if gap_kind is not None else ():
            if not any(kw in str(a).lower() for a in available):
                missing.append(kw)

        available = list(dict.fromkeys(available))[:10]
        missing = list(dict.fromkeys(missing))[:10]

        recommendation = (
            _RECOMMENDATIONS.get(gap_kind, _GENERIC_RECOMMENDATION)
            if gap_kind is not None
            else _GENERIC_RECOMMENDATION
        )

        impact = gap.get("impact") or {}
        return {
            "question": question,
            "gap_type": gap_type,
            "concept": concept,
            "available": available,
            "missing": missing,
            "recommendation": recommendation,
            "estimated_impact": {
                "query_count_30d": impact.get("query_count_30d", 0),
                "users": impact.get("users", 0),
                "agents": impact.get("agents", 0),
            },
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            t.lower()
            for t in _TOKEN_RE.findall(text or "")
            if len(t) > 1
        }

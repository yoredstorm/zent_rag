# =============================================================================
# Schema Linking — ranking semántico de tablas para el SQL Expert
# =============================================================================
# Pipeline deseado: Question -> concept extraction -> semantic catalog lookup
# -> candidate entities -> candidate tables -> relationship resolution ->
# minimal schema context -> SQL generation. Señales: glossary match, entity
# mapping, column/table descriptions, queries históricas exitosas, distancia
# de relaciones. Fallback al ranking heurístico si no hay catálogo.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import text

from src.catalog.store import PostgresCatalogStore
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9_]+")
_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "que", "con", "para", "por",
    "en", "un", "una", "cuantos", "cuantas", "cual", "cuales", "como",
    "estado", "actual", "tenemos", "hay", "what", "the", "and", "for",
    "our", "current", "how", "many", "which", "is", "are", "total",
}


def _tokens(text: str) -> set[str]:
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _STOPWORDS and len(t) > 1
    }


class SemanticSchemaLinking:
    """Calcula boosts semánticos por tabla para el ranking del SQL Expert."""

    def __init__(
        self,
        catalog_store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = catalog_store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    async def candidate_scores(
        self,
        organization_id: UUID,
        question: str,
        table_names: list[str],
    ) -> dict[str, float]:
        """Retorna {qualified_name: boost 0..1} para las tablas candidatas.

        Sin datos de catálogo retorna {} (el SQL Expert usa su heurística).
        """
        if not table_names:
            return {}
        tokens = _tokens(question)
        if not tokens:
            return {}

        scores: dict[str, float] = {}
        catalog_sources = await self._store.list_sources(organization_id)
        if not catalog_sources:
            return scores

        # 1) Glosario aprobado: conceptos/synonyms que aparecen en la pregunta.
        glossary_terms: dict[str, list[str]] = {}
        for source_row in catalog_sources:
            tables = await self._store.list_tables(organization_id, UUID(source_row["id"]))
            for t in tables:
                glossary_terms.setdefault(t["qualified_name"], [])

        # 2) Entidades mapeadas -> tablas (mapping semántico).
        entity_table_map: dict[str, str] = {}
        for entity in await self._store.list_entities(organization_id, limit=1000):
            if entity.get("mapped_table_id") and entity["status"] == "approved":
                row = await self._store.get_table(
                    organization_id, UUID(entity["mapped_table_id"])
                )
                if row:
                    entity_table_map[entity["name"].lower()] = row["qualified_name"]

        # 3) Descriptions (comentarios de tablas) como señal léxica.
        tables_with_meta: dict[str, dict] = {}
        for source_row in catalog_sources:
            for t in await self._store.list_tables(organization_id, UUID(source_row["id"])):
                tables_with_meta[t["qualified_name"]] = t

        # 4) Queries históricas exitosas (sql_audit_logs) -> frecuencia por tabla.
        historical: dict[str, int] = {}
        try:
            session = await get_async_session()
            try:
                rows = (
                    await session.execute(
                        text(
                            "SELECT generated_sql FROM sql_audit_logs "
                            "WHERE organization_id = :oid AND status = 'success' "
                            "ORDER BY created_at DESC LIMIT 200"
                        ),
                        {"oid": organization_id},
                    )
                ).fetchall()
            finally:
                await session.close()
            for row in rows:
                sql_lower = (row.generated_sql or "").lower()
                for name in table_names:
                    bare = name.split(".")[-1].lower()
                    if bare and f" {bare} " in f" {sql_lower} ":
                        historical[name] = historical.get(name, 0) + 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Historical schema signal failed", error=str(exc)[:200])

        # Glosario aprobado (concepto + synonyms) que matchee tokens.
        definitions = await self._intel.list_definitions(organization_id, status="approved")
        glossary_match_tables: dict[str, float] = {}
        for d in definitions:
            haystack = " ".join([d.concept, *d.synonyms])
            if any(t in haystack for t in tokens):
                for entity_name, qualified in entity_table_map.items():
                    if (
                        d.concept.split("_")[0] in entity_name
                        or entity_name.split("_")[0] in d.concept
                    ):
                        glossary_match_tables[qualified] = glossary_match_tables.get(
                            qualified, 0
                        ) + 1.0

        for name in table_names:
            boost = 0.0
            if name in glossary_match_tables:
                boost += 0.4 * min(glossary_match_tables[name], 2.0) / 2.0
            entity_name = next(
                (e for e, q in entity_table_map.items() if q == name), None
            )
            if entity_name and any(t in entity_name for t in tokens):
                boost += 0.3
            meta = tables_with_meta.get(name)
            if meta and meta.get("table_comment"):
                comment_tokens = _tokens(meta["table_comment"])
                if tokens & comment_tokens:
                    boost += 0.2
            hist = historical.get(name, 0)
            if hist:
                boost += 0.1 * min(hist, 10) / 10.0
            if boost > 0:
                scores[name] = round(min(boost, 1.0), 4)
        return scores

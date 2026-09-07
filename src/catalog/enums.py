# =============================================================================
# Enum Discovery — columnas categóricas y códigos desconocidos
# =============================================================================
# Detecta columnas categóricas (STATUS_CD -> A,B,C,I) y registra los valores
# como OBSERVED. Si no existe documentación aprobada, registra un gap
# UNDEFINED_ENUM y crea una sugerencia de revisión. NUNCA infiere
# automáticamente "A = Active" (puede sugerirlo con confidence, nunca
# aprobarlo).
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.core.domain.catalog import CatalogSuggestion, SuggestionType
from src.infrastructure.observability.logging_config import get_logger
from src.intelligence.store import PostgresIntelligenceStore

logger = get_logger(__name__)


class EnumDiscovery:
    """Procesa valores muestreados de columnas categóricas."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        intelligence_store: PostgresIntelligenceStore | None = None,
    ) -> None:
        self._store = store
        self._intel = intelligence_store or PostgresIntelligenceStore()

    async def process(
        self,
        *,
        organization_id: UUID,
        catalog_source_id: UUID,
        enum_columns: list[dict],
    ) -> list[dict]:
        """Persiste valores OBSERVED + gaps UNDEFINED_ENUM + sugerencias."""
        processed: list[dict] = []
        for info in enum_columns:
            table_id = UUID(info["table_id"])
            columns = await self._store.list_columns(organization_id, table_id)
            col_by_name = {c["column_name"]: c for c in columns}

            for column_name, values in info.get("samples", {}).items():
                column = col_by_name.get(column_name)
                if column is None:
                    continue
                column_id = UUID(column["id"])
                await self._store.upsert_enum_values(
                    organization_id=organization_id,
                    column_id=column_id,
                    values=list(values),
                )
                existing = await self._store.list_enum_values(
                    organization_id, column_id
                )
                documented = {
                    v["value"]
                    for v in existing
                    if v["status"] == "approved" and v.get("documented_meaning")
                }
                undocumented = [v for v in values if v not in documented]
                qualified = f"{info['schema']}.{info['table']}.{column_name}"
                processed.append(
                    {
                        "column_id": str(column_id),
                        "qualified": qualified,
                        "values": list(values),
                        "undocumented": undocumented,
                    }
                )
                if undocumented:
                    # Gap UNDEFINED_ENUM (context_gaps) para hacerlo accionable.
                    await self._intel.record_gap(
                        organization_id=organization_id,
                        gap_type="UNDEFINED_ENUM",
                        concept=qualified,
                        hints=list(values),
                    )
                    await self._ensure_suggestion(
                        organization_id=organization_id,
                        column_id=column_id,
                        column_name=column_name,
                        qualified=qualified,
                        values=list(values),
                        source_id=catalog_source_id,
                    )
        return processed

    async def _ensure_suggestion(
        self,
        *,
        organization_id: UUID,
        column_id: UUID,
        column_name: str,
        qualified: str,
        values: list[str],
        source_id: UUID,
    ) -> None:
        """Crea la sugerencia de definición de enum SOLO si no hay una pendiente."""
        pending = await self._store.list_suggestions(
            organization_id, status="pending", type="enum_definition", limit=100
        )
        for s in pending:
            if str(s["payload"].get("column_id")) == str(column_id):
                return
        suggestion = CatalogSuggestion(
            organization_id=organization_id,
            type=SuggestionType.ENUM_DEFINITION,
            title=f"'{qualified}' parece ser un catálogo de códigos sin descripción.",
            description=(
                f"La columna {column_name} tiene {len(values)} valores observados "
                f"sin significado documentado. No se infiere el significado "
                f"automáticamente: requiere revisión humana."
            ),
            evidence=["observado en metadata", f"valores: {', '.join(values[:10])}"],
            confidence="low",
            payload={
                "column_id": str(column_id),
                "column_name": column_name,
                "qualified": qualified,
                "values": list(values),
            },
            affected_sources=[str(source_id)],
        )
        await self._store.create_suggestion(suggestion)

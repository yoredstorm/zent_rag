# =============================================================================
# Relationship Discovery — FKs físicas + candidatos inferidos
# =============================================================================
# Registra las relaciones físicas declaradas (FK) y detecta candidatos cuando
# no existen FKs. Señales (sin tocar datos de producción): nombres, tipos,
# similitud de naming y metadata documentada. El solapamiento de valores es
# una señal opcional y desactivada por defecto (consulta de join con LIMIT 1).
# NUNCA crea constraints físicos en bases del cliente.
# =============================================================================
from __future__ import annotations

import re
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.connectors.plugin.models import DeepSchemaDiscovery
from src.core.domain.catalog import DiscoveryBudgets, RelationshipStatus
from src.core.domain.pii import is_sensitive_column
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

# Sufijos/prefijos de columnas llave (id/código/status).
_KEY_SUFFIXES = ("_id", "_cd", "_code", "_key", "_no", "_num")
_KEY_PREFIXES = ("id_", "cd_")
_STATUS_TERMS = ("status", "estado", "state", "cd", "code", "type", "tipo")
_REF_TABLE_HINT = re.compile(r"(.*?)(?:_cd|_code|_id|_key)$", re.IGNORECASE)


def _normalize_column(name: str) -> str:
    """Nombre de columna normalizado para matching (sin prefijos/sufijos)."""
    lower = name.lower()
    for suffix in _KEY_SUFFIXES:
        if lower.endswith(suffix) and len(lower) > len(suffix):
            lower = lower[: -len(suffix)]
    for prefix in _KEY_PREFIXES:
        if lower.startswith(prefix):
            lower = lower[len(prefix):]
    return lower.strip("_")


def _is_key_column(name: str, is_pk: bool = False) -> bool:
    if is_pk:
        return True
    lower = name.lower()
    return lower.endswith(_KEY_SUFFIXES) or lower.startswith(_KEY_PREFIXES)


def _is_status_code_column(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(t) or lower == t for t in _STATUS_TERMS)


def _types_compatible(a: str, b: str) -> bool:
    a_l, b_l = (a or "").lower(), (b or "").lower()
    if not a_l or not b_l:
        return True
    return a_l == b_l or a_l in b_l or b_l in a_l


class RelationshipDetector:
    """Detecta relaciones físicas y candidatas."""

    def __init__(
        self,
        store: PostgresCatalogStore,
        budgets: DiscoveryBudgets | None = None,
    ) -> None:
        self._store = store
        self._budgets = budgets or DiscoveryBudgets()

    async def detect(
        self,
        *,
        organization_id: UUID,
        catalog_source_id: UUID,
        deep: DeepSchemaDiscovery,
    ) -> list[dict]:
        """Persiste FKs físicas (confirmed) y candidatos inferidos (suggested)."""
        tables = await self._store.list_tables(organization_id, catalog_source_id)
        table_by_name: dict[str, dict] = {}
        for t in tables:
            table_by_name[f"{t['schema_name']}.{t['table_name']}"] = t
            table_by_name[t["table_name"]] = t

        results: list[dict] = []

        # 1) Relaciones físicas declaradas (FK) -> confirmed.
        for table in deep.tables:
            src = table_by_name.get(f"{table.schema}.{table.table_name}")
            if src is None:
                continue
            for fk in table.foreign_keys:
                dst = table_by_name.get(fk.to_table) or table_by_name.get(
                    _qualified(fk.to_table, table.schema)
                )
                if dst is None:
                    continue
                await self._store.upsert_relationship(
                    organization_id=organization_id,
                    source_id=catalog_source_id,
                    from_table_id=UUID(src["id"]),
                    from_column=fk.from_column,
                    to_table_id=UUID(dst["id"]),
                    to_column=fk.to_column,
                    relation_type="foreign_key",
                    confidence="high",
                    status=RelationshipStatus.CONFIRMED,
                    evidence=["declared foreign key"],
                )
                results.append(
                    {
                        "from": f"{src['qualified_name']}.{fk.from_column}",
                        "to": f"{dst['qualified_name']}.{fk.to_column}",
                        "relation_type": "foreign_key",
                        "status": "confirmed",
                    }
                )

        # 2) Candidatos inferidos cuando no hay FK declarada.
        existing_pairs: set[tuple[str, str]] = set()
        for rel in await self._store.list_relationships(
            organization_id, catalog_source_id
        ):
            existing_pairs.add((rel["from_table_id"], rel["to_table_id"]))

        for table in deep.tables:
            src = table_by_name.get(f"{table.schema}.{table.table_name}")
            if src is None:
                continue
            src_columns = {
                c.name: c for c in table.columns
            }
            for col_name, col in src_columns.items():
                if not _is_key_column(col_name, col.is_primary_key):
                    continue
                if is_sensitive_column(col_name):
                    continue
                norm = _normalize_column(col_name)
                if not norm or len(norm) < 2:
                    continue
                for other in deep.tables:
                    if f"{other.schema}.{other.table_name}" == f"{table.schema}.{table.table_name}":
                        continue
                    dst = table_by_name.get(f"{other.schema}.{other.table_name}")
                    if dst is None:
                        continue
                    if (src["id"], dst["id"]) in existing_pairs:
                        continue
                    for other_col in other.columns:
                        if other_col.name.lower() != col_name.lower():
                            continue
                        if is_sensitive_column(other_col.name):
                            continue
                        if not _types_compatible(col.data_type, other_col.data_type):
                            continue
                        confidence = "high" if (
                            _is_status_code_column(col_name)
                            and _is_status_code_column(other_col.name)
                        ) else "medium"
                        await self._store.upsert_relationship(
                            organization_id=organization_id,
                            source_id=catalog_source_id,
                            from_table_id=UUID(src["id"]),
                            from_column=col_name,
                            to_table_id=UUID(dst["id"]),
                            to_column=other_col.name,
                            relation_type="inferred",
                            confidence=confidence,
                            status=RelationshipStatus.SUGGESTED,
                            evidence=[
                                "column name match",
                                "data type match",
                                "naming similarity",
                            ],
                        )
                        results.append(
                            {
                                "from": f"{src['qualified_name']}.{col_name}",
                                "to": f"{dst['qualified_name']}.{other_col.name}",
                                "relation_type": "inferred",
                                "status": "suggested",
                                "confidence": confidence,
                            }
                        )
        return results


def _qualified(table_name: str, default_schema: str) -> str:
    if "." in table_name:
        return table_name
    return f"{default_schema}.{table_name}"


async def publish_relationship_suggestions(
    *,
    store: PostgresCatalogStore,
    organization_id: UUID,
    catalog_source_id: UUID,
) -> int:
    """Envía a Review Queue las relaciones sugeridas pendientes (idempotente).

    Reutilizable por el Discovery Engine y por el Knowledge Learning Engine:
    una FK física no es una relación de negocio aprobada hasta revisión.
    """
    from src.core.domain.catalog import CatalogSuggestion, SuggestionType

    stored_rels = await store.list_relationships(
        organization_id, catalog_source_id, status="suggested", limit=1000
    )
    pending = await store.list_suggestions(
        organization_id,
        status="pending",
        type="relationship_candidate",
        limit=1000,
    )
    already = {
        str((s.get("payload") or {}).get("relationship_id")) for s in pending
    }
    created = 0
    for rel in stored_rels:
        if rel["id"] in already:
            continue
        await store.create_suggestion(
            CatalogSuggestion(
                organization_id=organization_id,
                type=SuggestionType.RELATIONSHIP_CANDIDATE,
                title=(
                    f"Relación de negocio candidata: "
                    f"{rel['from_column']} → {rel['to_column']}"
                ),
                description=(
                    "FK físico no equivale a relación de negocio aprobada. "
                    "Confirmar o rechazar."
                ),
                evidence=rel.get("evidence") or ["inferred relationship"],
                confidence=rel.get("confidence") or "medium",
                payload={
                    "relationship_id": rel["id"],
                    "from_table_id": rel["from_table_id"],
                    "to_table_id": rel["to_table_id"],
                    "from_column": rel["from_column"],
                    "to_column": rel["to_column"],
                    "business_verb": "REFERENCES",
                },
                affected_sources=[str(catalog_source_id)],
            )
        )
        created += 1
    return created

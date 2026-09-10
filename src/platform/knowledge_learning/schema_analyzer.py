# =============================================================================
# Schema Analyzer — fingerprint y análisis estructural determinista (FASE 33)
# =============================================================================
# Construye el contexto físico por tabla (sin datos crudos) y un fingerprint
# estable basado en: nombre de tabla, columnas, tipos, PK, nullable y
# comentarios. El fingerprint permite cachear el análisis LLM (FASE 33B):
# si no cambia, no se repite la llamada al modelo.
# =============================================================================
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from uuid import UUID

from src.catalog.store import PostgresCatalogStore
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


def table_fingerprint(table: dict, columns: list[dict]) -> str:
    """Fingerprint de schema: metadata estructural, nunca valores de datos.

    Excluye intencionalmente row_count y null_ratio: cambios de datos no deben
    invalidar el entendimiento semántico.
    """
    payload = {
        "table": f"{table.get('schema_name', '')}.{table.get('table_name', '')}",
        "is_view": bool(table.get("is_view")),
        "comment": table.get("table_comment") or "",
        "columns": [
            {
                "name": c.get("column_name", ""),
                "type": c.get("data_type", ""),
                "nullable": bool(c.get("nullable", True)),
                "pk": bool(c.get("is_primary_key")),
                "comment": c.get("column_comment") or "",
                "sensitive": bool(c.get("is_sensitive")),
            }
            for c in sorted(columns, key=lambda item: item.get("column_name", ""))
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(kw_only=True)
class TableAnalysis:
    """Contexto físico por tabla para etapas semánticas (sanitizado)."""

    table_id: UUID
    qualified_name: str
    schema_name: str
    table_name: str
    fingerprint: str
    columns_total: int = 0
    columns_sensitive: int = 0
    primary_keys: list[str] = field(default_factory=list)
    foreign_key_columns: list[str] = field(default_factory=list)
    profiled_columns: int = 0


@dataclass(kw_only=True)
class SchemaAnalysis:
    tables: list[TableAnalysis] = field(default_factory=list)
    tables_total: int = 0
    tables_with_columns: int = 0
    columns_total: int = 0
    columns_sensitive: int = 0
    primary_keys_total: int = 0
    profiled_columns: int = 0
    fingerprints_updated: int = 0

    def to_metrics(self) -> dict:
        return {
            "tables_total": self.tables_total,
            "tables_with_columns": self.tables_with_columns,
            "columns_total": self.columns_total,
            "columns_sensitive": self.columns_sensitive,
            "primary_keys_total": self.primary_keys_total,
            "profiled_columns": self.profiled_columns,
            "fingerprints_updated": self.fingerprints_updated,
        }


class SchemaAnalyzer:
    """Análisis estructural determinista del catálogo físico de una fuente."""

    def __init__(self, store: PostgresCatalogStore) -> None:
        self._store = store

    async def analyze(
        self, organization_id: UUID, source_id: UUID
    ) -> SchemaAnalysis:
        analysis = SchemaAnalysis()
        tables = await self._store.list_tables(
            organization_id, source_id, limit=5000
        )
        analysis.tables_total = len(tables)

        relationships = await self._store.list_relationships(
            organization_id, source_id, limit=5000
        )
        fk_columns_by_table: dict[str, set[str]] = {}
        for rel in relationships:
            if rel.get("relation_type") != "foreign_key":
                continue
            fk_columns_by_table.setdefault(rel["from_table_id"], set()).add(
                rel["from_column"]
            )

        for table in tables:
            columns = await self._store.list_columns(
                organization_id, UUID(table["id"])
            )
            if columns:
                analysis.tables_with_columns += 1
            analysis.columns_total += len(columns)

            fingerprint = table_fingerprint(table, columns)
            primary_keys = [
                c["column_name"] for c in columns if c.get("is_primary_key")
            ]
            sensitive = [c for c in columns if c.get("is_sensitive")]
            profiled = [
                c for c in columns if c.get("null_ratio") is not None
            ]
            analysis.columns_sensitive += len(sensitive)
            analysis.primary_keys_total += len(primary_keys)
            analysis.profiled_columns += len(profiled)

            try:
                updated = await self._store.update_table_fingerprint(
                    organization_id,
                    UUID(table["id"]),
                    fingerprint,
                    previous=table.get("schema_fingerprint"),
                )
                if updated:
                    analysis.fingerprints_updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Table fingerprint update failed",
                    table=table.get("qualified_name"),
                    error=str(exc)[:200],
                )

            analysis.tables.append(
                TableAnalysis(
                    table_id=UUID(table["id"]),
                    qualified_name=table.get("qualified_name")
                    or table.get("table_name", ""),
                    schema_name=table.get("schema_name", ""),
                    table_name=table.get("table_name", ""),
                    fingerprint=fingerprint,
                    columns_total=len(columns),
                    columns_sensitive=len(sensitive),
                    primary_keys=primary_keys,
                    foreign_key_columns=sorted(
                        fk_columns_by_table.get(table["id"], set())
                    ),
                    profiled_columns=len(profiled),
                )
            )
        return analysis

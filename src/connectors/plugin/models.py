# =============================================================================
# Connector Platform — modelos de discovery
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(kw_only=True)
class ColumnSchema:
    name: str
    data_type: str
    nullable: bool = True
    default: str | None = None
    is_primary_key: bool = False


@dataclass(kw_only=True)
class IndexInfo:
    name: str
    columns: list[str]
    unique: bool = False


@dataclass(kw_only=True)
class Relationship:
    """Arista FK: columna origen apunta a otra tabla."""

    from_column: str
    to_table: str
    to_column: str


@dataclass(kw_only=True)
class TableSchema:
    name: str
    schema: str = ""
    columns: list[ColumnSchema] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[Relationship] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    row_count: int | None = None
    is_view: bool = False

    @property
    def relationships(self) -> list[Relationship]:
        return self.foreign_keys


@dataclass(kw_only=True)
class SchemaDiscovery:
    """Resultado de discover(): estructura completa de la fuente."""

    tables: list[TableSchema] = field(default_factory=list)
    source: str = ""
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "tables": [
                {
                    "name": t.name,
                    "schema": t.schema,
                    "row_count": t.row_count,
                    "is_view": t.is_view,
                    "primary_keys": t.primary_keys,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "nullable": c.nullable,
                            "default": c.default,
                            "is_primary_key": c.is_primary_key,
                        }
                        for c in t.columns
                    ],
                    "foreign_keys": [
                        {
                            "from_column": r.from_column,
                            "to_table": r.to_table,
                            "to_column": r.to_column,
                        }
                        for r in t.foreign_keys
                    ],
                    "indexes": [
                        {"name": i.name, "columns": i.columns, "unique": i.unique}
                        for i in t.indexes
                    ],
                }
                for t in self.tables
            ],
            "source": self.source,
            "discovered_at": self.discovered_at.isoformat(),
        }


@dataclass(kw_only=True)
class ColumnProfile:
    """Perfil de columna para deep discovery (FASE 24 — Discovery Engine).

    Los valores son OBSERVED (metadata/estadísticas de la fuente); nunca se
    ejecutan consultas agresivas sobre datos de producción.
    """

    name: str
    data_type: str = ""
    nullable: bool = True
    is_primary_key: bool = False
    column_comment: str | None = None
    null_ratio: float | None = None  # 0..1 (o None si la fuente no lo expone)
    cardinality: int | None = None  # n_distinct aproximado (OBSERVED)
    distinct_values: list[str] = field(default_factory=list)  # muestras OBSERVED
    pii_flags: list[str] = field(default_factory=list)
    sensitive: bool = False
    sample_disabled: bool = False


@dataclass(kw_only=True)
class DeepTableProfile:
    """Perfil profundo de una tabla (deep_discover)."""

    table_name: str
    schema: str = ""
    is_view: bool = False
    row_count_approx: int | None = None
    table_comment: str | None = None
    columns: list[ColumnProfile] = field(default_factory=list)
    foreign_keys: list[Relationship] = field(default_factory=list)


@dataclass(kw_only=True)
class DeepSchemaDiscovery:
    """Resultado de deep_discover(): estructura + perfiles seguros."""

    tables: list[DeepTableProfile] = field(default_factory=list)
    source: str = ""
    discovered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "tables": [
                {
                    "table_name": t.table_name,
                    "schema": t.schema,
                    "is_view": t.is_view,
                    "row_count_approx": t.row_count_approx,
                    "table_comment": t.table_comment,
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "nullable": c.nullable,
                            "is_primary_key": c.is_primary_key,
                            "column_comment": c.column_comment,
                            "null_ratio": c.null_ratio,
                            "cardinality": c.cardinality,
                            "distinct_values": c.distinct_values[:50],
                            "pii_flags": c.pii_flags,
                            "sensitive": c.sensitive,
                            "sample_disabled": c.sample_disabled,
                        }
                        for c in t.columns
                    ],
                    "foreign_keys": [
                        {
                            "from_column": r.from_column,
                            "to_table": r.to_table,
                            "to_column": r.to_column,
                        }
                        for r in t.foreign_keys
                    ],
                }
                for t in self.tables
            ],
            "source": self.source,
            "discovered_at": self.discovered_at.isoformat(),
        }

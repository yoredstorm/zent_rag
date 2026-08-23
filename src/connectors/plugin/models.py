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

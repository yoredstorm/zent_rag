# =============================================================================
# PostgreSQL plugin — conexión, test y schema discovery
# =============================================================================
from __future__ import annotations

import time
from typing import ClassVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.connectors.plugin.base import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
)
from src.connectors.plugin.models import (
    ColumnProfile,
    ColumnSchema,
    DeepSchemaDiscovery,
    DeepTableProfile,
    IndexInfo,
    Relationship,
    SchemaDiscovery,
    TableSchema,
)
from src.core.config import get_settings
from src.core.domain.pii import is_sensitive_column, pii_flags_for_column

_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}


class PostgresPlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "postgres"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["password"]

    def _dsn(self) -> str:
        config = self.config
        host = str(config.get("host") or "").strip()
        port = int(config.get("port") or 5432)
        database = str(config.get("database") or "").strip()
        user = str(config.get("user") or "").strip()
        password = str(self.secrets.get("password") or "")
        if not host or not database or not user:
            raise ConnectorError(
                "postgres config requires host, database and user"
            )
        if not password:
            raise ConnectorError("postgres requires secret: password")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{host}:{port}/{database}"
        )

    async def validate(self) -> None:
        config = self.config
        host = str(config.get("host") or "").strip()
        if not host:
            raise ConnectorError("postgres config requires host")
        assert_host_safe(host, allowlist=config.get("ssrf_allowlist"))
        if not self.secrets.get("password"):
            raise ConnectorError("postgres requires secret: password")

    async def connect(self) -> None:
        self._engine = create_async_engine(
            self._dsn(), pool_pre_ping=True, poolclass=None
        )
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except ConnectorError:
            raise
        except Exception as exc:
            await self.close()
            raise ConnectorError(f"Connection failed: {exc}") from exc

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            await self.connect()
            async with self._engine.connect() as conn:  # type: ignore[union-attr]
                row = (await conn.execute(text("SELECT version()"))).fetchone()
            version = str(row[0])[:120] if row else None
            return ConnectionTestResult(
                ok=True,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="ok",
                server_version=version,
            )
        except ConnectorError as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=str(exc),
            )
        finally:
            await self.close()

    async def discover(self) -> SchemaDiscovery:
        await self.connect()
        try:
            max_tables = int(get_settings().CONNECTOR_DISCOVER_MAX_TABLES)
            async with self._engine.connect() as conn:  # type: ignore[union-attr]
                tables = await self._discover_tables(conn, max_tables)
                for table in tables:
                    table.columns = await self._discover_columns(conn, table)
                    table.indexes = await self._discover_indexes(conn, table)
                # Row counts baratos vía reltuples (aprox).
                for table in tables:
                    table.row_count = await self._row_count(conn, table)
            return SchemaDiscovery(tables=tables, source="postgres")
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Discovery failed: {exc}") from exc
        finally:
            await self.close()

    async def _discover_tables(self, conn, max_tables: int) -> list[TableSchema]:
        rows = (
            await conn.execute(
                text(
                    "SELECT table_schema, table_name, table_type "
                    "FROM information_schema.tables "
                    "WHERE table_schema NOT IN :excluded "
                    "ORDER BY table_schema, table_name LIMIT :limit"
                ).bindparams(
                    excluded=tuple(sorted(_SYSTEM_SCHEMAS)),
                    limit=max_tables,
                )
            )
        ).fetchall()
        return [
            TableSchema(
                name=row.table_name,
                schema=row.table_schema,
                is_view=row.table_type == "VIEW",
            )
            for row in rows
        ]

    async def _discover_columns(self, conn, table: TableSchema) -> list[ColumnSchema]:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.column_name, c.data_type, c.is_nullable, "
                    "c.column_default, "
                    "(tc.constraint_type = 'PRIMARY KEY') AS is_pk "
                    "FROM information_schema.columns c "
                    "LEFT JOIN information_schema.table_constraints tc "
                    "  ON tc.table_schema = c.table_schema "
                    " AND tc.table_name = c.table_name "
                    " AND tc.constraint_type = 'PRIMARY KEY' "
                    "LEFT JOIN information_schema.key_column_usage kcu "
                    "  ON kcu.constraint_name = tc.constraint_name "
                    " AND kcu.column_name = c.column_name "
                    " AND kcu.table_schema = c.table_schema "
                    "WHERE c.table_schema = :schema AND c.table_name = :table "
                    "ORDER BY c.ordinal_position"
                ),
                {"schema": table.schema, "table": table.name},
            )
        ).fetchall()
        return [
            ColumnSchema(
                name=row.column_name,
                data_type=str(row.data_type),
                nullable=row.is_nullable == "YES",
                default=(
                    str(row.column_default)[:200]
                    if row.column_default is not None
                    else None
                ),
                is_primary_key=bool(row.is_pk),
            )
            for row in rows
        ]

    async def _discover_indexes(self, conn, table: TableSchema) -> list[IndexInfo]:
        rows = (
            await conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": table.schema, "table": table.name},
            )
        ).fetchall()
        indexes: list[IndexInfo] = []
        for row in rows:
            import re as _re

            cols = _re.findall(r"\(([^)]+)\)", row.indexdef or "")
            columns = (
                [c.strip().strip('"') for c in cols[-1].split(",")]
                if cols
                else []
            )
            indexes.append(
                IndexInfo(
                    name=row.indexname,
                    columns=columns,
                    unique="UNIQUE" in (row.indexdef or "").upper(),
                )
            )
        return indexes

    async def _row_count(self, conn, table: TableSchema) -> int | None:
        try:
            row = (
                await conn.execute(
                    text(
                        "SELECT reltuples::bigint FROM pg_class "
                        "JOIN pg_namespace n ON n.oid = relnamespace "
                        "WHERE n.nspname = :schema AND relname = :table"
                    ),
                    {"schema": table.schema, "table": table.name},
                )
            ).fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    async def deep_discover(self, max_samples: int = 50) -> DeepSchemaDiscovery:
        """Discovery profundo read-only: comentarios, FKs y estadísticas pg_stats.

        Los perfiles provienen de metadata/estadísticas del catálogo (pg_stats),
        NO de consultas sobre datos de producción.
        """
        await self.connect()
        try:
            async with self._engine.connect() as conn:  # type: ignore[union-attr]
                discovery = await self.discover()
                tables: list[DeepTableProfile] = []
                for table in discovery.tables:
                    table_comment = await self._table_comment(conn, table)
                    stats = await self._column_stats(conn, table, max_samples)
                    fks = await self._foreign_keys(conn, table)
                    columns = []
                    for c in table.columns:
                        stat = stats.get(c.name)
                        columns.append(
                            ColumnProfile(
                                name=c.name,
                                data_type=c.data_type,
                                nullable=c.nullable,
                                is_primary_key=c.is_primary_key,
                                column_comment=stat.get("comment") if stat else None,
                                null_ratio=stat.get("null_frac") if stat else None,
                                cardinality=stat.get("n_distinct") if stat else None,
                                distinct_values=stat.get("common_vals") or [],
                                pii_flags=pii_flags_for_column(c.name),
                                sensitive=is_sensitive_column(c.name),
                                sample_disabled=is_sensitive_column(c.name),
                            )
                        )
                    tables.append(
                        DeepTableProfile(
                            table_name=table.name,
                            schema=table.schema,
                            is_view=table.is_view,
                            row_count_approx=table.row_count,
                            table_comment=table_comment,
                            columns=columns,
                            foreign_keys=fks,
                        )
                    )
            return DeepSchemaDiscovery(tables=tables, source="postgres")
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Deep discovery failed: {exc}") from exc
        finally:
            await self.close()

    async def _table_comment(self, conn, table: TableSchema) -> str | None:
        try:
            row = (
                await conn.execute(
                    text(
                        "SELECT obj_description(c.oid) "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema AND c.relname = :table"
                    ),
                    {"schema": table.schema, "table": table.name},
                )
            ).fetchone()
            return str(row[0])[:2000] if row and row[0] else None
        except Exception:
            return None

    async def _column_stats(
        self, conn, table: TableSchema, max_samples: int
    ) -> dict[str, dict]:
        """null_frac / n_distinct / most_common_vals desde pg_stats (OBSERVED)."""
        out: dict[str, dict] = {}
        try:
            rows = (
                await conn.execute(
                    text(
                        "SELECT attname, null_frac, n_distinct, "
                        "most_common_vals::text, most_common_freqs::text "
                        "FROM pg_stats "
                        "WHERE schemaname = :schema AND tablename = :table"
                    ),
                    {"schema": table.schema, "table": table.name},
                )
            ).fetchall()
            for row in rows:
                n_distinct = row.n_distinct
                if n_distinct is None:
                    cardinality = None
                elif n_distinct < 0:
                    cardinality = None
                else:
                    cardinality = int(n_distinct)
                common_vals: list[str] = []
                if row.most_common_vals:
                    raw = str(row.most_common_vals)
                    if raw.startswith("{") and raw.endswith("}"):
                        common_vals = [
                            v.strip('"') for v in raw[1:-1].split(",") if v.strip() != ""
                        ]
                out[row.attname] = {
                    "null_frac": round(float(row.null_frac), 4) if row.null_frac is not None else None,
                    "n_distinct": cardinality,
                    "common_vals": common_vals[: max(int(max_samples), 10)],
                    "comment": None,
                }
        except Exception:
            pass
        # Comentarios de columna (independiente de pg_stats).
        try:
            rows = (
                await conn.execute(
                    text(
                        "SELECT a.attname, col_description(c.oid, a.attnum) AS comment "
                        "FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid "
                        "WHERE n.nspname = :schema AND c.relname = :table "
                        "AND a.attnum > 0 AND NOT a.attisdropped"
                    ),
                    {"schema": table.schema, "table": table.name},
                )
            ).fetchall()
            for row in rows:
                if row.comment:
                    entry = out.setdefault(row.attname, {"comment": None})
                    entry["comment"] = str(row.comment)[:2000]
        except Exception:
            pass
        return out

    async def _foreign_keys(self, conn, table: TableSchema) -> list[Relationship]:
        try:
            rows = (
                await conn.execute(
                    text(
                        "SELECT kcu.column_name AS from_column, "
                        "ccu.table_name AS to_table, ccu.column_name AS to_column "
                        "FROM information_schema.table_constraints tc "
                        "JOIN information_schema.key_column_usage kcu "
                        "  ON tc.constraint_name = kcu.constraint_name "
                        " AND tc.table_schema = kcu.table_schema "
                        "JOIN information_schema.constraint_column_usage ccu "
                        "  ON ccu.constraint_name = tc.constraint_name "
                        " AND ccu.constraint_schema = tc.table_schema "
                        "WHERE tc.constraint_type = 'FOREIGN KEY' "
                        "AND tc.table_schema = :schema AND tc.table_name = :table"
                    ),
                    {"schema": table.schema, "table": table.name},
                )
            ).fetchall()
            return [
                Relationship(
                    from_column=r.from_column,
                    to_table=r.to_table,
                    to_column=r.to_column,
                )
                for r in rows
            ]
        except Exception:
            return []

    async def sample_distinct_values(
        self, schema: str, table: str, column: str, max_samples: int = 50
    ) -> list[str]:
        """Muestreo acotado de valores distintos (solo lectura, LIMIT).

        La capa de profiling decide cuándo invocarlo (nunca para columnas
        sensibles; presupuesto de queries por scan).
        """
        from src.connectors.sql.schema_discovery import quote_ident

        try:
            schema_ident = quote_ident(schema)
            table_ident = quote_ident(table)
            col_ident = quote_ident(column)
        except ValueError:
            return []
        try:
            await self.connect()
            try:
                async with self._engine.connect() as conn:  # type: ignore[union-attr]
                    rows = (
                        await conn.execute(  # noqa: S608 — identifiers quote_ident-validados
                            text(
                                f"SELECT DISTINCT {col_ident} FROM "
                                f"{schema_ident}.{table_ident} "
                                f"WHERE {col_ident} IS NOT NULL "
                                f"ORDER BY 1 LIMIT {int(max_samples)}"
                            )
                        )
                    ).fetchall()
                    return [str(r[0])[:200] for r in rows]
            finally:
                await self.close()
        except Exception:
            return []

    async def close(self) -> None:
        engine = getattr(self, "_engine", None)
        if engine is not None:
            await engine.dispose()
            self._engine = None

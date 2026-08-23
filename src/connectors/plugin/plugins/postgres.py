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
    ColumnSchema,
    IndexInfo,
    SchemaDiscovery,
    TableSchema,
)
from src.core.config import get_settings

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

    async def close(self) -> None:
        engine = getattr(self, "_engine", None)
        if engine is not None:
            await engine.dispose()
            self._engine = None

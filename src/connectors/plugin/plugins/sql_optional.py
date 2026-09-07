# =============================================================================
# SQL plugins opcionales — MySQL, SQL Server, Oracle, DB2
# =============================================================================
# Drivers opcionales (extras de pyproject): aiomysql, pyodbc, oracledb,
# ibm_db_sa. Sin el driver instalado, el plugin lanza ConnectorError claro
# "instala el extra". Ejecución sync vía asyncio.to_thread (no bloquea loop).
#
# FASE 24 — Discovery Engine:
#   - MySQL/MSSQL: discover (estructura) + deep_discover (comentarios + FKs).
#   - Oracle/DB2: discover de tablas/columnas implementado (catálogos all_* /
#     syscat). La cardinalidad/null_ratio se exponen solo vía
#     sample_distinct_values (llamado por el profiler con presupuesto y
#     nunca para columnas sensibles).
# =============================================================================
from __future__ import annotations

import asyncio
import re
import time
from typing import ClassVar

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
    Relationship,
    SchemaDiscovery,
    TableSchema,
)
from src.core.domain.pii import is_sensitive_column, pii_flags_for_column

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(name: str) -> str:
    if not _IDENT_RE.match(name or ""):
        raise ValueError(f"Unsafe identifier: {name}")
    return name


class _SyncSqlPlugin(ConnectorPlugin):
    """Base para SQL plugins con drivers sync (MySQL/MSSQL/Oracle/DB2)."""

    driver_module: ClassVar[str] = ""
    extra_name: ClassVar[str] = ""

    def _engine(self):
        raise NotImplementedError

    def _import_driver(self):
        try:
            return __import__(self.driver_module, fromlist=["*"])
        except ImportError:
            raise ConnectorError(
                f"{self.connector_type} driver not installed. "
                f"Install the extra: pip install .[{self.extra_name}]"
            ) from None

    def _sync_test(self) -> tuple[bool, str, str | None]:
        self._import_driver()
        engine = self._engine()
        try:
            with engine.connect() as conn:
                row = conn.exec_driver_sql(self._version_query()).fetchone()
                return True, "ok", (str(row[0])[:120] if row else None)
        except Exception as exc:
            return False, f"Connection failed: {exc}", None
        finally:
            engine.dispose()

    def _sync_discover_tables(self, max_tables: int) -> list[TableSchema]:
        self._import_driver()
        engine = self._engine()
        try:
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(
                    self._tables_query(max_tables)
                ).fetchall()
                tables: list[TableSchema] = []
                for row in rows:
                    table = TableSchema(
                        name=str(row[1]),
                        schema=str(row[0]) if row[0] is not None else "",
                    )
                    tables.append(table)
                for table in tables:
                    cols = conn.exec_driver_sql(
                        self._columns_query(table), {"schema": table.schema, "table": table.name}
                    ).fetchall() if self._columns_query(table) else []
                    table.columns = [
                        ColumnSchema(
                            name=str(c[0]),
                            data_type=str(c[1]) if len(c) > 1 else "unknown",
                            nullable=bool(c[2]) if len(c) > 2 else True,
                        )
                        for c in cols
                    ]
                return tables
        finally:
            engine.dispose()

    def _version_query(self) -> str:
        return "SELECT 1"

    def _tables_query(self, max_tables: int) -> str:
        return "SELECT NULL, NULL LIMIT 0"

    def _columns_query(self, table: TableSchema) -> str:
        return ""

    # ---- deep discovery hooks (default: sin metadata extra) -------------
    def _table_comment_query(self) -> str:
        return ""

    def _column_comment_query(self) -> str:
        return ""

    def _fk_query(self) -> str:
        return ""

    def _distinct_query(
        self, schema: str, table: str, column: str, max_samples: int
    ) -> str:
        return ""

    def _sync_deep_table(
        self, conn, table: TableSchema, max_samples: int
    ) -> DeepTableProfile:
        table_comment: str | None = None
        if self._table_comment_query():
            try:
                row = conn.exec_driver_sql(
                    self._table_comment_query(),
                    {"schema": table.schema, "table": table.name},
                ).fetchone()
                table_comment = str(row[0])[:2000] if row and row[0] else None
            except Exception:
                table_comment = None

        fks: list[Relationship] = []
        if self._fk_query():
            try:
                rows = conn.exec_driver_sql(
                    self._fk_query(),
                    {"schema": table.schema, "table": table.name},
                ).fetchall()
                fks = [
                    Relationship(
                        from_column=str(r[0]),
                        to_table=str(r[1]),
                        to_column=str(r[2]),
                    )
                    for r in rows
                ]
            except Exception:
                fks = []

        columns = []
        for c in table.columns:
            comment: str | None = None
            if self._column_comment_query():
                try:
                    row = conn.exec_driver_sql(
                        self._column_comment_query(),
                        {"schema": table.schema, "table": table.name, "column": c.name},
                    ).fetchone()
                    comment = str(row[0])[:2000] if row and row[0] else None
                except Exception:
                    comment = None
            columns.append(
                ColumnProfile(
                    name=c.name,
                    data_type=c.data_type,
                    nullable=c.nullable,
                    is_primary_key=c.is_primary_key,
                    column_comment=comment,
                    pii_flags=pii_flags_for_column(c.name),
                    sensitive=is_sensitive_column(c.name),
                    sample_disabled=is_sensitive_column(c.name),
                )
            )
        return DeepTableProfile(
            table_name=table.name,
            schema=table.schema,
            is_view=table.is_view,
            table_comment=table_comment,
            columns=columns,
            foreign_keys=fks,
        )

    async def validate(self) -> None:
        host = str(self.config.get("host") or "").strip()
        if not host:
            raise ConnectorError(f"{self.connector_type} config requires host")
        assert_host_safe(host, allowlist=self.config.get("ssrf_allowlist"))
        if not self.secrets.get("password"):
            raise ConnectorError(
                f"{self.connector_type} requires secret: password"
            )

    async def connect(self) -> None:
        # Conexión efímera: test/discover abren y cierran su propio engine.
        await asyncio.to_thread(self._import_driver)

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            ok, message, version = await asyncio.to_thread(self._sync_test)
        except ConnectorError as exc:
            ok, message, version = False, str(exc), None
        return ConnectionTestResult(
            ok=ok,
            latency_ms=(time.perf_counter() - start) * 1000,
            message=message,
            server_version=version,
        )

    async def discover(self) -> SchemaDiscovery:
        from src.core.config import get_settings

        max_tables = int(get_settings().CONNECTOR_DISCOVER_MAX_TABLES)
        try:
            tables = await asyncio.to_thread(
                self._sync_discover_tables, max_tables
            )
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Discovery failed: {exc}") from exc
        return SchemaDiscovery(tables=tables, source=self.connector_type)

    async def deep_discover(self, max_samples: int = 50) -> DeepSchemaDiscovery:
        from src.core.config import get_settings

        max_tables = int(get_settings().CONNECTOR_DISCOVER_MAX_TABLES)

        def _run() -> list[DeepTableProfile]:
            self._import_driver()
            engine = self._engine()
            try:
                with engine.connect() as conn:
                    rows = conn.exec_driver_sql(
                        self._tables_query(max_tables)
                    ).fetchall()
                    out: list[DeepTableProfile] = []
                    for row in rows:
                        table = TableSchema(
                            name=str(row[1]),
                            schema=str(row[0]) if row[0] is not None else "",
                        )
                        cols = (
                            conn.exec_driver_sql(
                                self._columns_query(table),
                                {"schema": table.schema, "table": table.name},
                            ).fetchall()
                            if self._columns_query(table)
                            else []
                        )
                        table.columns = [
                            ColumnSchema(
                                name=str(c[0]),
                                data_type=str(c[1]) if len(c) > 1 else "unknown",
                                nullable=bool(c[2]) if len(c) > 2 else True,
                            )
                            for c in cols
                        ]
                        out.append(self._sync_deep_table(conn, table, max_samples))
                    return out
            finally:
                engine.dispose()

        try:
            tables = await asyncio.to_thread(_run)
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Deep discovery failed: {exc}") from exc
        return DeepSchemaDiscovery(tables=tables, source=self.connector_type)

    async def sample_distinct_values(
        self, schema: str, table: str, column: str, max_samples: int = 50
    ) -> list[str]:
        query = self._distinct_query(schema, table, column, max_samples)
        if not query:
            return []

        def _run() -> list[str]:
            self._import_driver()
            engine = self._engine()
            try:
                with engine.connect() as conn:
                    rows = conn.exec_driver_sql(query).fetchall()
                    return [str(r[0])[:200] for r in rows]
            finally:
                engine.dispose()

        try:
            return await asyncio.to_thread(_run)
        except Exception:
            return []


class MysqlPlugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "mysql"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["password"]
    driver_module: ClassVar[str] = "aiomysql"
    extra_name: ClassVar[str] = "connectors"

    def _engine(self):
        from sqlalchemy import create_engine

        config = self.config
        return create_engine(
            "mysql+pymysql://{user}:{password}@{host}:{port}/{database}".format(
                user=config.get("user", ""),
                password=self.secrets.get("password", ""),
                host=config.get("host", ""),
                port=int(config.get("port") or 3306),
                database=config.get("database", ""),
            ),
            pool_pre_ping=True,
        )

    def _version_query(self) -> str:
        return "SELECT VERSION()"

    def _tables_query(self, max_tables: int) -> str:
        return (
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN "
            "('information_schema','mysql','performance_schema','sys') "
            "ORDER BY table_schema, table_name LIMIT " + str(int(max_tables))
        )

    def _columns_query(self, table: TableSchema) -> str:
        return (
            "SELECT column_name, data_type, is_nullable = 'YES' "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table "
            "ORDER BY ordinal_position"
        )

    def _table_comment_query(self) -> str:
        return (
            "SELECT table_comment FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = :table"
        )

    def _column_comment_query(self) -> str:
        return (
            "SELECT column_comment FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table "
            "AND column_name = :column"
        )

    def _fk_query(self) -> str:
        return (
            "SELECT column_name, referenced_table_name, referenced_column_name "
            "FROM information_schema.key_column_usage "
            "WHERE table_schema = :schema AND table_name = :table "
            "AND referenced_table_name IS NOT NULL"
        )

    def _distinct_query(
        self, schema: str, table: str, column: str, max_samples: int
    ) -> str:
        return (
            f"SELECT DISTINCT `{_safe_ident(column)}` FROM "
            f"`{_safe_ident(schema)}`.`{_safe_ident(table)}` "
            f"WHERE `{_safe_ident(column)}` IS NOT NULL "
            f"ORDER BY 1 LIMIT {int(max_samples)}"
        )


class MssqlPlugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "mssql"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["password"]
    driver_module: ClassVar[str] = "pyodbc"
    extra_name: ClassVar[str] = "connectors"

    def _engine(self):
        from sqlalchemy import create_engine

        config = self.config
        return create_engine(
            "mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+18+for+SQL+Server".format(
                user=config.get("user", ""),
                password=self.secrets.get("password", ""),
                host=config.get("host", ""),
                port=int(config.get("port") or 1433),
                database=config.get("database", ""),
            ),
            pool_pre_ping=True,
        )

    def _version_query(self) -> str:
        return "SELECT @@VERSION"

    def _tables_query(self, max_tables: int) -> str:
        return (
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' "
            "ORDER BY table_schema, table_name "
            "OFFSET 0 ROWS FETCH NEXT " + str(int(max_tables)) + " ROWS ONLY"
        )

    def _columns_query(self, table: TableSchema) -> str:
        return (
            "SELECT column_name, data_type, is_nullable = 'YES' "
            "FROM information_schema.columns "
            "WHERE table_schema = :schema AND table_name = :table "
            "ORDER BY ordinal_position"
        )

    def _fk_query(self) -> str:
        return (
            "SELECT COL_NAME(fk.parent_object_id, fkc.parent_column_id), "
            "OBJECT_NAME(fk.referenced_object_id), "
            "COL_NAME(fk.referenced_object_id, fkc.referenced_column_id) "
            "FROM sys.foreign_keys fk "
            "JOIN sys.foreign_key_columns fkc "
            "  ON fk.object_id = fkc.constraint_object_id "
            "WHERE OBJECT_SCHEMA_NAME(fk.parent_object_id) = :schema "
            "AND OBJECT_NAME(fk.parent_object_id) = :table"
        )

    def _distinct_query(
        self, schema: str, table: str, column: str, max_samples: int
    ) -> str:
        return (
            f"SELECT DISTINCT [{_safe_ident(column)}] FROM "
            f"[{_safe_ident(schema)}].[{_safe_ident(table)}] "
            f"WHERE [{_safe_ident(column)}] IS NOT NULL "
            f"ORDER BY 1 OFFSET 0 ROWS FETCH NEXT {int(max_samples)} ROWS ONLY"
        )


class OraclePlugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "oracle"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["password"]
    driver_module: ClassVar[str] = "oracledb"
    extra_name: ClassVar[str] = "connectors"

    def _engine(self):
        from sqlalchemy import create_engine

        config = self.config
        return create_engine(
            "oracle+oracledb://{user}:{password}@{host}:{port}/?service_name={service}".format(
                user=config.get("user", ""),
                password=self.secrets.get("password", ""),
                host=config.get("host", ""),
                port=int(config.get("port") or 1521),
                service=config.get("service_name", ""),
            ),
            pool_pre_ping=True,
        )

    def _version_query(self) -> str:
        return "SELECT banner FROM v$version WHERE ROWNUM = 1"

    def _tables_query(self, max_tables: int) -> str:
        return (
            "SELECT owner, table_name FROM all_tables "
            "ORDER BY owner, table_name FETCH FIRST "
            + str(int(max_tables))
            + " ROWS ONLY"
        )

    def _columns_query(self, table: TableSchema) -> str:
        return (
            "SELECT column_name, data_type, nullable = 'Y' "
            "FROM all_tab_columns WHERE owner = :schema "
            "AND table_name = :table ORDER BY column_id"
        )

    def _table_comment_query(self) -> str:
        return (
            "SELECT comments FROM all_tab_comments "
            "WHERE owner = :schema AND table_name = :table"
        )

    def _column_comment_query(self) -> str:
        return (
            "SELECT comments FROM all_col_comments "
            "WHERE owner = :schema AND table_name = :table "
            "AND column_name = :column"
        )

    def _fk_query(self) -> str:
        return (
            "SELECT ac.column_name, rcc.table_name, rcc.column_name "
            "FROM all_constraints c "
            "JOIN all_cons_columns ac "
            "  ON c.constraint_name = ac.constraint_name AND c.owner = ac.owner "
            "JOIN all_constraints rc "
            "  ON c.r_constraint_name = rc.constraint_name AND rc.owner = c.owner "
            "JOIN all_cons_columns rcc "
            "  ON rc.constraint_name = rcc.constraint_name "
            " AND rcc.position = ac.position AND rcc.owner = rc.owner "
            "WHERE c.constraint_type = 'R' AND c.owner = :schema "
            "AND c.table_name = :table"
        )

    def _distinct_query(
        self, schema: str, table: str, column: str, max_samples: int
    ) -> str:
        return (
            f"SELECT DISTINCT \"{_safe_ident(column)}\" FROM "
            f"\"{_safe_ident(schema)}\".\"{_safe_ident(table)}\" "
            f"WHERE \"{_safe_ident(column)}\" IS NOT NULL "
            f"AND ROWNUM <= {int(max_samples)}"
        )


class Db2Plugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "db2"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["password"]
    driver_module: ClassVar[str] = "ibm_db_sa"
    extra_name: ClassVar[str] = "connectors"

    def _engine(self):
        from sqlalchemy import create_engine

        config = self.config
        return create_engine(
            "db2+ibm_db://{user}:{password}@{host}:{port}/{database}".format(
                user=config.get("user", ""),
                password=self.secrets.get("password", ""),
                host=config.get("host", ""),
                port=int(config.get("port") or 50000),
                database=config.get("database", ""),
            ),
            pool_pre_ping=True,
        )

    def _version_query(self) -> str:
        return "SELECT service_level FROM table(sysproc.env_get_inst_info())"

    def _tables_query(self, max_tables: int) -> str:
        return (
            "SELECT TRIM(tabschema), tabname FROM syscat.tables "
            "WHERE tabschema NOT LIKE 'SYS%' "
            "ORDER BY tabschema, tabname FETCH FIRST "
            + str(int(max_tables))
            + " ROWS ONLY"
        )

    def _columns_query(self, table: TableSchema) -> str:
        return (
            "SELECT TRIM(colname), typename, nulls = 'N' "
            "FROM syscat.columns WHERE tabschema = :schema "
            "AND tabname = :table ORDER BY colno"
        )

    def _table_comment_query(self) -> str:
        return (
            "SELECT remarks FROM syscat.tables "
            "WHERE tabschema = :schema AND tabname = :table"
        )

    def _column_comment_query(self) -> str:
        return (
            "SELECT remarks FROM syscat.columns "
            "WHERE tabschema = :schema AND tabname = :table "
            "AND colname = :column"
        )

    def _fk_query(self) -> str:
        return (
            "SELECT TRIM(fkcol.colname), TRIM(r.tabname), TRIM(pkcol.colname) "
            "FROM syscat.references r "
            "JOIN syscat.keycoluse fkcol "
            "  ON fkcol.constname = r.constname AND fkcol.tabschema = r.tabschema "
            " AND fkcol.tabname = r.tabname "
            "JOIN syscat.keycoluse pkcol "
            "  ON pkcol.constname = r.refkeyname AND pkcol.colseq = fkcol.colseq "
            "WHERE r.tabschema = :schema AND r.tabname = :table"
        )

    def _distinct_query(
        self, schema: str, table: str, column: str, max_samples: int
    ) -> str:
        return (
            f"SELECT DISTINCT \"{_safe_ident(column)}\" FROM "
            f"\"{_safe_ident(schema)}\".\"{_safe_ident(table)}\" "
            f"WHERE \"{_safe_ident(column)}\" IS NOT NULL "
            f"FETCH FIRST {int(max_samples)} ROWS ONLY"
        )


def register() -> None:
    """Registra los plugins SQL opcionales (llamado por el package init)."""
    from src.connectors.plugin.registry import register_plugin

    register_plugin(MysqlPlugin)
    register_plugin(MssqlPlugin)
    register_plugin(OraclePlugin)
    register_plugin(Db2Plugin)

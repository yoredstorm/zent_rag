# =============================================================================
# SQL plugins opcionales — MySQL, SQL Server, Oracle, DB2
# =============================================================================
# Drivers opcionales (extras de pyproject): aiomysql, pyodbc, oracledb,
# ibm_db_sa. Sin el driver instalado, el plugin lanza ConnectorError claro
# "instala el extra". Ejecución sync vía asyncio.to_thread (no bloquea loop).
# Discovery se implementa por information_schema (MySQL) o catálogo básico.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from typing import ClassVar

from src.connectors.plugin.base import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
    assert_host_safe,
)
from src.connectors.plugin.models import ColumnSchema, SchemaDiscovery, TableSchema


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


class OraclePlugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "oracle"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test"})
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


class Db2Plugin(_SyncSqlPlugin):
    connector_type: ClassVar[str] = "db2"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test"})
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


def register() -> None:
    """Registra los plugins SQL opcionales (llamado por el package init)."""
    from src.connectors.plugin.registry import register_plugin

    register_plugin(MysqlPlugin)
    register_plugin(MssqlPlugin)
    register_plugin(OraclePlugin)
    register_plugin(Db2Plugin)

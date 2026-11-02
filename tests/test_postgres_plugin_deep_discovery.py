# =============================================================================
# Regresion: deep_discover sin pg_stats no debe romper con stat=None.
# =============================================================================
from __future__ import annotations

import pytest

from src.connectors.plugin.models import ColumnSchema, SchemaDiscovery, TableSchema
from src.connectors.plugin.plugins.postgres import PostgresPlugin


class _Conn:
    pass


class _ConnContext:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *args):
        return False


class _Engine:
    def connect(self):
        return _ConnContext()


@pytest.mark.asyncio
async def test_deep_discover_without_pg_stats() -> None:
    plugin = PostgresPlugin.__new__(PostgresPlugin)
    plugin._engine = _Engine()
    plugin.config = {}
    plugin.secrets = {}

    async def _connect():
        return None

    async def _discover():
        return SchemaDiscovery(
            tables=[
                TableSchema(
                    name="fresh_table",
                    schema="public",
                    columns=[ColumnSchema(name="id", data_type="uuid")],
                )
            ],
            source="postgres",
        )

    async def _stats(*_args, **_kwargs):
        return {}

    async def _comment(*_args, **_kwargs):
        return None

    async def _fks(*_args, **_kwargs):
        return []

    async def _close():
        return None

    plugin.connect = _connect  # type: ignore[method-assign]
    plugin.discover = _discover  # type: ignore[method-assign]
    plugin._column_stats = _stats  # type: ignore[method-assign]
    plugin._table_comment = _comment  # type: ignore[method-assign]
    plugin._foreign_keys = _fks  # type: ignore[method-assign]
    plugin.close = _close  # type: ignore[method-assign]

    result = await plugin.deep_discover()
    assert len(result.tables) == 1
    assert result.tables[0].columns[0].distinct_values == []
    assert result.tables[0].columns[0].null_ratio is None

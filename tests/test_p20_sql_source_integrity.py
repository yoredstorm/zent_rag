# =============================================================================
# P20-01 - La fuente SQL externa no se indexa contra la BD interna de ZENT.
# =============================================================================
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.knowledge.connectors.base import ConnectorError
from src.knowledge.connectors.sql_source import SQLSourceConnector


def _external_source():
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        config_json={
            "connector_id": str(uuid4()),
            "source_mode": "schema_only",
            "engine": "postgres",
        },
    )


@pytest.mark.asyncio
async def test_external_sql_source_rejects_internal_validate() -> None:
    connector = SQLSourceConnector(_external_source())
    with pytest.raises(ConnectorError) as exc:
        await connector.validate()
    assert "SOURCE_MODE_UNSUPPORTED" in str(exc.value)


@pytest.mark.asyncio
async def test_external_sql_source_rejects_internal_discover() -> None:
    connector = SQLSourceConnector(_external_source())
    with pytest.raises(ConnectorError) as exc:
        await connector.discover()
    assert "SOURCE_MODE_UNSUPPORTED" in str(exc.value)


@pytest.mark.asyncio
async def test_external_sql_source_rejects_internal_sync() -> None:
    connector = SQLSourceConnector(_external_source())
    with pytest.raises(ConnectorError) as exc:
        await connector.sync(None)
    assert "SOURCE_MODE_UNSUPPORTED" in str(exc.value)


def test_full_refresh_is_not_org_wide() -> None:
    from pathlib import Path

    source = Path("src/connectors/sql/ingestion.py").read_text(encoding="utf-8")
    assert "delete_by_organization" not in source
    assert "FULL_REFRESH_UNSUPPORTED" in source

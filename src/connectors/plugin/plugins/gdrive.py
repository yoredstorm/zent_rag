# =============================================================================
# Google Drive plugin — folder_id en config; refresh_token en SecretStore
# =============================================================================
from __future__ import annotations

import time
from typing import ClassVar

from src.connectors.gdrive.client import (
    list_folder_files,
    refresh_access_token,
)
from src.connectors.plugin.base import (
    ConnectionTestResult,
    ConnectorError,
    ConnectorPlugin,
)
from src.connectors.plugin.models import SchemaDiscovery, TableSchema


class GDrivePlugin(ConnectorPlugin):
    connector_type: ClassVar[str] = "gdrive"
    capabilities: ClassVar[frozenset[str]] = frozenset({"test", "discover"})
    required_secret_keys: ClassVar[list[str]] = ["refresh_token"]

    def _folder_id(self) -> str:
        folder_id = str(self.config.get("folder_id") or "").strip()
        if not folder_id:
            raise ConnectorError("gdrive config requires folder_id")
        return folder_id

    async def validate(self) -> None:
        self._folder_id()
        if not str(self.secrets.get("refresh_token") or "").strip():
            raise ConnectorError("gdrive requires secrets: refresh_token")

    async def connect(self) -> None:
        await self.validate()
        try:
            await refresh_access_token(str(self.secrets["refresh_token"]))
        except Exception as exc:
            raise ConnectorError(f"Drive token refresh failed: {exc}") from exc

    async def test_connection(self) -> ConnectionTestResult:
        start = time.perf_counter()
        try:
            await self.validate()
            token = await refresh_access_token(str(self.secrets["refresh_token"]))
            await list_folder_files(token, self._folder_id())
            return ConnectionTestResult(
                ok=True,
                latency_ms=(time.perf_counter() - start) * 1000,
                message="ok",
            )
        except ConnectorError as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=str(exc),
            )
        except Exception as exc:
            return ConnectionTestResult(
                ok=False,
                latency_ms=(time.perf_counter() - start) * 1000,
                message=f"Drive check failed: {exc}",
            )

    async def discover(self) -> SchemaDiscovery:
        await self.validate()
        token = await refresh_access_token(str(self.secrets["refresh_token"]))
        files = await list_folder_files(token, self._folder_id())
        tables = [
            TableSchema(name=str(item.get("name") or item.get("id") or "file"))
            for item in files
        ]
        return SchemaDiscovery(tables=tables, source="gdrive")


def register() -> None:
    from src.connectors.plugin.registry import register_plugin

    register_plugin(GDrivePlugin)

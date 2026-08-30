# =============================================================================
# GDriveSourceConnector — carpeta de Drive → Markdown vía normalizers existentes
# =============================================================================
# config: { folder_id, connector_id }
# secrets: refresh_token en SecretStore(organization_id, connector_id) — nunca
# en config_json. Isolation: se carga con el org de la fuente, no del cliente.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from src.connectors.gdrive.client import (
    download_file,
    extension_for_file,
    list_folder_files,
    refresh_access_token,
)
from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.normalize.base import NormalizerError, get_normalizer


class GDriveSourceConnector(SourceConnector):
    source_type = "gdrive"
    self_contained = False

    def __init__(self, source) -> None:
        super().__init__(source)
        self.secrets: dict = {}

    def _folder_id(self) -> str:
        folder_id = str(self.config.get("folder_id") or "").strip()
        if not folder_id:
            raise ConnectorError("gdrive source requires 'folder_id' in config")
        return folder_id

    def _connector_id(self) -> UUID:
        raw = self.config.get("connector_id")
        if not raw:
            raise ConnectorError("gdrive source requires 'connector_id' in config")
        try:
            return UUID(str(raw))
        except ValueError as exc:
            raise ConnectorError("gdrive connector_id must be a UUID") from exc

    async def _ensure_secrets(self) -> dict:
        if str(self.secrets.get("refresh_token") or "").strip():
            return self.secrets
        from src.infrastructure.secrets.secret_store_resolver import get_secret_store

        loaded = await get_secret_store().get(
            self.source.organization_id, self._connector_id()
        )
        self.secrets = dict(loaded or {})
        return self.secrets

    async def validate(self) -> None:
        self._folder_id()
        self._connector_id()
        secrets = await self._ensure_secrets()
        if not str(secrets.get("refresh_token") or "").strip():
            raise ConnectorError(
                "gdrive refresh_token secret is not configured for this organization"
            )

    async def discover(self) -> list[DiscoveredItem]:
        await self.validate()
        token = await refresh_access_token(str(self.secrets["refresh_token"]))
        items: list[DiscoveredItem] = []
        for file in await list_folder_files(token, self._folder_id()):
            name = str(file.get("name") or file.get("id") or "file")
            items.append(
                DiscoveredItem(
                    external_id=str(file.get("id") or name),
                    label=name,
                    extra={"mime_type": file.get("mimeType")},
                )
            )
        return items

    async def iter_records(self, cursor: dict | None):
        import src.knowledge.normalize  # noqa: F401

        await self.validate()
        token = await refresh_access_token(str(self.secrets["refresh_token"]))
        done_keys: set[str] = set(cursor.get("done_keys", [])) if cursor else set()
        max_objects = int(self.config.get("max_objects") or 100)
        count = 0
        for file in await list_folder_files(token, self._folder_id()):
            if count >= max_objects:
                break
            file_id = str(file.get("id") or "")
            name = str(file.get("name") or file_id)
            mime = str(file.get("mimeType") or "")
            if not file_id or file_id in done_keys:
                continue
            ext = extension_for_file(name, mime)
            if ext is None:
                continue
            normalizer = get_normalizer(ext)
            if normalizer is None:
                continue
            try:
                data = await download_file(token, file_id, mime)
                markdown = normalizer.normalize(data, source_name=name)
            except (NormalizerError, ValueError) as exc:
                raise ConnectorError(f"Drive read failed for {name}: {exc}") from exc
            count += 1
            done_keys.add(file_id)
            yield Record(
                external_id=file_id,
                content=markdown,
                metadata={
                    "filename": name,
                    "format": ext,
                    "folder_id": self._folder_id(),
                    "mime_type": mime,
                },
            )
            self._last_cursor = {"done_keys": sorted(done_keys)}

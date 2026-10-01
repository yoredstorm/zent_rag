# =============================================================================
# FileSourceConnector — archivos subidos (txt/md/json/pdf/docx/html)
# =============================================================================
from __future__ import annotations

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.storage import resolve_path


class FileSourceConnector(SourceConnector):
    source_type = "file"
    self_contained = False

    async def validate(self) -> None:
        object_key = self.config.get("object_key", "")
        if not object_key:
            raise ConnectorError("file source requires 'object_key' in config")
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")

    async def discover(self) -> list[DiscoveredItem]:
        path = self._path()
        return [
            DiscoveredItem(
                external_id=self.config.get("object_key", ""),
                label=path.name,
                extra={"size_bytes": path.stat().st_size if path.exists() else 0},
            )
        ]

    def _path(self):
        return resolve_path(self.source.organization_id, self.config.get("object_key", ""))

    async def iter_records(self, cursor: dict | None):
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {path.name}")
        from src.knowledge.structure import get_parser, supported_extensions

        data = path.read_bytes()
        extension = path.suffix.lower().lstrip(".")
        if get_parser(extension) is None:
            raise ConnectorError(
                f"Unsupported file type '.{extension}'. "
                f"Supported: {', '.join(supported_extensions())}"
            )
        yield Record(
            external_id=self.config.get("object_key", path.name),
            content=path.name,
            metadata={
                "filename": path.name,
                "format": extension,
                "size_bytes": path.stat().st_size,
            },
            raw_data=data,
            format=extension,
        )

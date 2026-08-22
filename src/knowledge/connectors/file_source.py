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
from src.knowledge.normalize.base import NormalizerError, get_normalizer
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
        data = path.read_bytes()
        extension = path.suffix.lower()
        normalizer = get_normalizer(extension)
        if normalizer is None:
            raise ConnectorError(
                f"Unsupported file type '{extension}'. "
                f"Supported: {', '.join(sorted([e for e in ['txt', 'md', 'json', 'pdf', 'docx', 'html']]))}"
            )
        try:
            markdown = normalizer.normalize(data, source_name=path.name)
        except NormalizerError as exc:
            raise ConnectorError(str(exc)) from exc
        yield Record(
            external_id=self.config.get("object_key", path.name),
            content=markdown,
            metadata={"filename": path.name, "format": extension.lstrip(".")},
        )

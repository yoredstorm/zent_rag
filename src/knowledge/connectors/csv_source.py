# =============================================================================
# CSVSourceConnector — filas → Records "campo: valor" (tabla markdown)
# =============================================================================
from __future__ import annotations

import csv
import io

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.storage import resolve_path


def rows_to_records(
    rows: list[dict[str, str]],
    external_prefix: str,
    *,
    extra_metadata: dict | None = None,
) -> list[Record]:
    """Serializa filas dict a Records legibles por LLM."""
    records: list[Record] = []
    for index, row in enumerate(rows):
        lines = [f"{key}: {value}" for key, value in row.items() if value not in (None, "")]
        if not lines:
            continue
        metadata = {"row_index": index, **(extra_metadata or {})}
        records.append(
            Record(
                external_id=f"{external_prefix}:row:{index}",
                content="\n".join(lines),
                metadata=metadata,
            )
        )
    return records


class CSVSourceConnector(SourceConnector):
    source_type = "csv"
    self_contained = False

    def _delimiter(self) -> str:
        return (self.config.get("delimiter") or ",")[:1]

    async def validate(self) -> None:
        object_key = self.config.get("object_key", "")
        if not object_key:
            raise ConnectorError("csv source requires 'object_key' in config")
        path = resolve_path(self.source.organization_id, object_key)
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        try:
            text = path.read_text(encoding=self.config.get("encoding") or "utf-8-sig")
            reader = csv.reader(io.StringIO(text), delimiter=self._delimiter())
            next(reader, None)
        except Exception as exc:
            raise ConnectorError(f"CSV parse failed: {exc}") from exc

    async def discover(self) -> list[DiscoveredItem]:
        path = resolve_path(self.source.organization_id, self.config.get("object_key", ""))
        return [
            DiscoveredItem(
                external_id=self.config.get("object_key", ""),
                label=path.name,
                extra={},
            )
        ]

    async def iter_records(self, cursor: dict | None):
        object_key = self.config.get("object_key", "")
        path = resolve_path(self.source.organization_id, object_key)
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        text = path.read_text(encoding=self.config.get("encoding") or "utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), delimiter=self._delimiter())
        for record in rows_to_records(
            list(reader), object_key, extra_metadata={"format": "csv"}
        ):
            yield record

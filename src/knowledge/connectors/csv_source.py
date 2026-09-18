# =============================================================================
# CSVSourceConnector — filas → Records "campo: valor" (tabla markdown)
# =============================================================================
# V1: cada fila es un Record "campo: valor" (compatibilidad total).
# V2/Tabular: el PRIMER record transporta los bytes originales + external_id
# del documento para el parser CSV del pipeline tabular (una sola vez).
# =============================================================================
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from pathlib import Path

from src.core.config import get_settings
from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.storage import resolve_path


def iter_rows_as_records(
    rows: Iterable[dict[str, str]],
    external_prefix: str,
    *,
    extra_metadata: dict | None = None,
) -> Iterator[Record]:
    """Serializa filas dict a Records legibles por LLM (streaming)."""
    for index, row in enumerate(rows):
        lines = [
            f"{key}: {value}"
            for key, value in row.items()
            if value not in (None, "")
        ]
        if not lines:
            continue
        metadata = {"row_index": index, **(extra_metadata or {})}
        yield Record(
            external_id=f"{external_prefix}:row:{index}",
            content="\n".join(lines),
            metadata=metadata,
        )


def rows_to_records(
    rows: list[dict[str, str]],
    external_prefix: str,
    *,
    extra_metadata: dict | None = None,
) -> list[Record]:
    """Compatibilidad: versión lista de `iter_rows_as_records`."""
    return list(
        iter_rows_as_records(rows, external_prefix, extra_metadata=extra_metadata)
    )


class CSVSourceConnector(SourceConnector):
    source_type = "csv"
    self_contained = False

    def _delimiter(self) -> str:
        return (self.config.get("delimiter") or ",")[:1]

    def _path(self):
        return resolve_path(
            self.source.organization_id, self.config.get("object_key", "")
        )

    async def validate(self) -> None:
        object_key = self.config.get("object_key", "")
        if not object_key:
            raise ConnectorError("csv source requires 'object_key' in config")
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        try:
            text = path.read_text(encoding=self.config.get("encoding") or "utf-8-sig")
            reader = csv.reader(io.StringIO(text), delimiter=self._delimiter())
            next(reader, None)
        except Exception as exc:
            raise ConnectorError(f"CSV parse failed: {exc}") from exc

    async def discover(self) -> list[DiscoveredItem]:
        path = self._path()
        return [
            DiscoveredItem(
                external_id=self.config.get("object_key", ""),
                label=path.name,
                extra={},
            )
        ]

    async def iter_records(self, cursor: dict | None):
        object_key = self.config.get("object_key", "")
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        data = path.read_bytes()
        extension = Path(object_key or path.name).suffix.lower().lstrip(".") or "csv"
        if self._supersede_v1():
            yield Record(
                external_id=object_key,
                content=self._summary_content(path, data, extension),
                metadata={
                    "filename": self.config.get("filename") or path.name,
                    "format": "csv",
                    "document_external_id": object_key,
                    "supersede_v1": True,
                },
                raw_data=data,
                format=extension,
            )
            return
        text = data.decode(self.config.get("encoding") or "utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=self._delimiter())
        first = True
        for record in iter_rows_as_records(
            reader, object_key, extra_metadata={"format": "csv"}
        ):
            if first:
                first = False
                metadata = {
                    **record.metadata,
                    "document_external_id": object_key,
                    "filename": self.config.get("filename") or path.name,
                }
                yield Record(
                    external_id=record.external_id,
                    content=record.content,
                    metadata=metadata,
                    raw_data=data,
                    format=extension,
                )
            else:
                yield record

    def _supersede_v1(self) -> bool:
        """True si V1 debe emitir un solo resumen (flag global o del source)."""
        settings = get_settings()
        if not (settings.KNOWLEDGE_V2_ENABLED and settings.KNOWLEDGE_TABULAR_ENABLED):
            return False
        override = self.config.get("supersede_v1")
        if override is not None:
            return bool(override)
        return bool(getattr(settings, "KNOWLEDGE_TABULAR_SUPERSEDE_V1", False))

    def _summary_content(self, path, data: bytes, extension: str) -> str:
        """Resumen compacto del CSV (dialecto + headers) para el índice V1."""
        text = data.decode(self.config.get("encoding") or "utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter=self._delimiter())
        header = next(reader, []) or []
        return "\n".join(
            [
                f"Workbook: {path.name}",
                f"Format: {extension}",
                "Columns: " + ", ".join(str(value).strip() for value in header[:30]),
                "Full row/column structure indexed by Knowledge Tabular V2 (SQL-first).",
            ]
        )

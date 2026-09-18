# =============================================================================
# ExcelSourceConnector — hojas → filas → Records (openpyxl, MIT)
# =============================================================================
# V1: cada fila es un Record "campo: valor" (compatibilidad total).
# V2/Tabular: el PRIMER record del sync transporta los bytes originales
# (raw_data + format) y el external_id del workbook, para que el pipeline
# estructurado parsee el archivo UNA sola vez (no una vez por fila).
# =============================================================================
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from src.core.config import get_settings
from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
from src.knowledge.connectors.csv_source import rows_to_records
from src.knowledge.storage import resolve_path


class ExcelSourceConnector(SourceConnector):
    source_type = "excel"
    self_contained = False

    def _sheet(self) -> str | None:
        return self.config.get("sheet") or None

    def _path(self):
        return resolve_path(
            self.source.organization_id, self.config.get("object_key", "")
        )

    async def validate(self) -> None:
        object_key = self.config.get("object_key", "")
        if not object_key:
            raise ConnectorError("excel source requires 'object_key' in config")
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        try:
            import openpyxl

            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                sheet_name = self._sheet() or workbook.sheetnames[0]
                if sheet_name not in workbook.sheetnames:
                    raise ConnectorError(f"Sheet '{sheet_name}' not found in workbook")
            finally:
                workbook.close()
        except ConnectorError:
            raise
        except Exception as exc:
            raise ConnectorError(f"Excel parse failed: {exc}") from exc

    def _load_sheet(self, path) -> list[dict[str, str]]:
        """Compatibilidad: carga la hoja V1 completa (listas pequeñas/tests)."""
        return list(self._iter_sheet_rows(path))

    def _iter_sheet_rows(self, path) -> Iterator[dict[str, str]]:
        """Itera la hoja V1 en streaming (sin cargar todo el workbook)."""
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            sheet_name = self._sheet() or workbook.sheetnames[0]
            if sheet_name not in workbook.sheetnames:
                raise ConnectorError(f"Sheet '{sheet_name}' not found in workbook")
            sheet = workbook[sheet_name]
            rows_iter = sheet.iter_rows(values_only=True)
            headers = [str(h).strip() if h is not None else "" for h in next(rows_iter, ())]
            headers = [h or f"col_{i}" for i, h in enumerate(headers)]
            for row in rows_iter:
                if row is None or all(v is None for v in row):
                    continue
                yield {
                    headers[i]: "" if v is None else str(v)
                    for i, v in enumerate(row)
                    if i < len(headers)
                }
        finally:
            workbook.close()

    async def discover(self) -> list[DiscoveredItem]:
        import openpyxl

        path = self._path()
        workbook = openpyxl.load_workbook(path, read_only=True)
        try:
            sheets = list(workbook.sheetnames)
        finally:
            workbook.close()
        return [
            DiscoveredItem(external_id=f"sheet:{s}", label=s, extra={"rows": "?"})
            for s in sheets
        ]

    async def iter_records(self, cursor: dict | None):
        object_key = self.config.get("object_key", "")
        path = self._path()
        if not path.exists():
            raise ConnectorError(f"Uploaded file not found: {object_key}")
        data = path.read_bytes()
        extension = Path(object_key or path.name).suffix.lower().lstrip(".") or "xlsx"
        if self._supersede_v1():
            # Knowledge Tabular V2: la estructura fila/columna vive en el
            # pipeline tabular; V1 solo indexa un resumen del archivo.
            yield Record(
                external_id=object_key,
                content=self._summary_content(path, extension),
                metadata={
                    "filename": self.config.get("filename") or object_key,
                    "format": "excel",
                    "document_external_id": object_key,
                    "supersede_v1": True,
                },
                raw_data=data,
                format=extension,
            )
            return
        records = rows_to_records(
            self._iter_sheet_rows(path),
            object_key,
            extra_metadata={"format": "excel", "sheet": self._sheet()},
        )
        first = True
        for record in records:
            if first:
                first = False
                yield self._with_document_payload(record, data, extension, object_key)
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

    def _summary_content(self, path, extension: str) -> str:
        """Resumen compacto del workbook (hojas + headers) para el índice V1."""
        lines = [f"Workbook: {path.name}", f"Format: {extension}"]
        try:
            import openpyxl

            workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
            try:
                lines.append(f"Sheets: {len(workbook.sheetnames)}")
                for name in workbook.sheetnames:
                    header = next(workbook[name].iter_rows(values_only=True), ()) or ()
                    columns = [
                        str(value).strip() for value in header if value is not None
                    ][:30]
                    lines.append(f"Sheet '{name}' columns: " + ", ".join(columns))
            finally:
                workbook.close()
        except Exception:  # noqa: BLE001 - el resumen nunca rompe la ingesta
            pass
        lines.append(
            "Full row/column structure indexed by Knowledge Tabular V2 (SQL-first)."
        )
        return "\n".join(lines)

    def _with_document_payload(
        self, record: Record, data: bytes, extension: str, external_id: str
    ) -> Record:
        """Adjunta bytes/formato al primer record para el pipeline V2 tabular."""
        metadata = {
            **record.metadata,
            "document_external_id": external_id,
            "filename": self.config.get("filename") or external_id,
        }
        return Record(
            external_id=record.external_id,
            content=record.content,
            metadata=metadata,
            raw_data=data,
            format=extension,
        )

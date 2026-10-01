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

from src.knowledge.connectors.base import (
    ConnectorError,
    DiscoveredItem,
    Record,
    SourceConnector,
)
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
        # La estructura fila/columna vive en la representación tabular; el
        # índice textual solo guarda un resumen del archivo.
        yield Record(
            external_id=object_key,
            content=self._summary_content(path, extension),
            metadata={
                "filename": self.config.get("filename") or object_key,
                "format": "excel",
                "document_external_id": object_key,
            },
            raw_data=data,
            format=extension,
        )

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

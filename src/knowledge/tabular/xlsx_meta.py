# =============================================================================
# Tabular ingestion — metadatos XLSX sin cargar el workbook (stdlib XML)
# =============================================================================
# openpyxl en read_only pierde merged cells, filas/columnas ocultas y Tables
# formales. Este lector abre el ZIP y extrae SOLO metadatos estructurales con
# presupuesto de bytes (anti zip-bomb): dimensiones, merged ranges, hidden,
# Tables y conteo de formulas. Nunca evalúa ni ejecuta nada.
# =============================================================================
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from src.core.domain.tabular import CellRange

_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_RANGE_RE = re.compile(r"^([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?$")


class XlsxMetaError(ValueError):
    """XLSX ilegible o por encima de los límites de seguridad."""


@dataclass(frozen=True, kw_only=True)
class SheetMeta:
    name: str
    path: str
    state: str = "visible"
    dimension: CellRange | None = None
    merged: tuple[CellRange, ...] = ()
    hidden_rows: frozenset[int] = frozenset()
    hidden_columns: frozenset[int] = frozenset()
    excel_tables: tuple["TableMeta", ...] = ()
    formula_count: int = 0
    truncated: bool = False


@dataclass(frozen=True, kw_only=True)
class TableMeta:
    name: str
    ref: CellRange | None
    header_row_count: int = 1
    totals_row_count: int = 0
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WorkbookMeta:
    sheets: tuple[SheetMeta, ...] = ()
    truncated: bool = False


def column_number(letters: str) -> int:
    value = 0
    for char in letters.upper():
        if not ("A" <= char <= "Z"):
            raise ValueError(f"invalid column letters: {letters!r}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


def parse_range(ref: str) -> CellRange | None:
    match = _RANGE_RE.match((ref or "").strip().upper())
    if not match:
        return None
    min_col = column_number(match.group(1))
    min_row = int(match.group(2))
    max_col = column_number(match.group(3)) if match.group(3) else min_col
    max_row = int(match.group(4)) if match.group(4) else min_row
    if min_row < 1 or min_col < 1 or max_row < min_row or max_col < min_col:
        return None
    return CellRange(min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col)


def read_workbook_meta(
    data: bytes,
    *,
    max_uncompressed_bytes: int = 512 * 1024 * 1024,
    max_entry_bytes: int = 128 * 1024 * 1024,
) -> WorkbookMeta:
    """Extrae metadatos estructurales del XLSX sin abrir el workbook completo.

    Lanza XlsxMetaError si el archivo no es un ZIP/OOXML válido o si excede el
    presupuesto de bytes descomprimidos (zip bomb).
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = {info.filename: info for info in archive.infolist()}
            total_uncompressed = sum(info.file_size for info in infos.values())
            if total_uncompressed > max_uncompressed_bytes:
                raise XlsxMetaError(
                    f"xlsx uncompressed size {total_uncompressed} exceeds limit "
                    f"{max_uncompressed_bytes}"
                )
            oversized = [
                name
                for name, info in infos.items()
                if info.file_size > max_entry_bytes
            ]
            if oversized:
                raise XlsxMetaError(f"xlsx entry too large: {oversized[:3]}")

            workbook_xml = _read_member(archive, "xl/workbook.xml", 8 * 1024 * 1024)
            rels_xml = _read_member(
                archive, "xl/_rels/workbook.xml.rels", 4 * 1024 * 1024
            )
            if workbook_xml is None or rels_xml is None:
                raise XlsxMetaError("xlsx is missing xl/workbook.xml or its rels")

            rel_map = _read_relationships(rels_xml, _PKG_REL_NS)
            sheets: list[SheetMeta] = []
            truncated = False
            for index, sheet_el in enumerate(_iter_sheets(workbook_xml)):
                name = sheet_el.get("name") or f"Sheet{index + 1}"
                state = sheet_el.get("state") or "visible"
                rel_id = sheet_el.get(f"{{{_REL_NS}}}id") or sheet_el.get("id")
                target = rel_map.get(rel_id or "")
                if not target or not _is_worksheet_target(target):
                    continue
                path = _normalize_target(target)
                sheet_data = _read_member(archive, path, max_entry_bytes)
                if sheet_data is None:
                    continue
                meta = _parse_sheet_meta(
                    name=name,
                    path=path,
                    state=state,
                    sheet_xml=sheet_data,
                    archive=archive,
                    max_entry_bytes=max_entry_bytes,
                )
                sheets.append(meta)
                truncated = truncated or meta.truncated
            return WorkbookMeta(sheets=tuple(sheets), truncated=truncated)
    except zipfile.BadZipFile as exc:
        raise XlsxMetaError(f"xlsx is not a valid zip archive: {exc}") from exc


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit:
        # Leer solo hasta el límite: metadatos incompletos, nunca OOM.
        with archive.open(info) as handle:
            return handle.read(limit)
    with archive.open(info) as handle:
        return handle.read()


def _read_relationships(xml_bytes: bytes, namespace: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        root = ElementTree.fromstring(xml_bytes)  # noqa: S314 (bytes acotados por presupuesto anti zip-bomb)
    except ElementTree.ParseError:
        return result
    for rel in root.iter(f"{{{namespace}}}Relationship"):
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if rel_id and target:
            result[rel_id] = target
    return result


def _iter_sheets(workbook_xml: bytes):
    try:
        root = ElementTree.fromstring(workbook_xml)  # noqa: S314 (bytes acotados por presupuesto anti zip-bomb)
    except ElementTree.ParseError as exc:
        raise XlsxMetaError(f"invalid xl/workbook.xml: {exc}") from exc
    return root.iter(f"{{{_SHEET_NS}}}sheet")


def _is_worksheet_target(target: str) -> bool:
    lowered = target.lower()
    return lowered.endswith(".xml") and "/worksheets/" in _normalize_target(lowered)


def _normalize_target(target: str) -> str:
    cleaned = target.lstrip("/").replace("\\", "/")
    if cleaned.startswith("xl/"):
        return cleaned
    return f"xl/{cleaned}"


def _parse_sheet_meta(
    *,
    name: str,
    path: str,
    state: str,
    sheet_xml: bytes,
    archive: zipfile.ZipFile,
    max_entry_bytes: int,
) -> SheetMeta:
    dimension: CellRange | None = None
    merged: list[CellRange] = []
    hidden_rows: set[int] = set()
    hidden_columns: set[int] = set()
    excel_tables: list[TableMeta] = []
    formula_count = 0
    truncated = False

    try:
        root = ElementTree.fromstring(sheet_xml)  # noqa: S314 (bytes acotados por presupuesto anti zip-bomb)
    except ElementTree.ParseError as exc:
        raise XlsxMetaError(f"invalid worksheet XML {path}: {exc}") from exc

    dimension_el = root.find(f"{{{_SHEET_NS}}}dimension")
    if dimension_el is not None:
        dimension = parse_range(dimension_el.get("ref") or "")

    for row_el in root.iter(f"{{{_SHEET_NS}}}row"):
        if (row_el.get("hidden") or "") in ("1", "true"):
            try:
                hidden_rows.add(int(row_el.get("r") or 0))
            except ValueError:
                continue
        for cell_el in row_el.iter(f"{{{_SHEET_NS}}}c"):
            if cell_el.find(f"{{{_SHEET_NS}}}f") is not None:
                formula_count += 1

    cols_el = root.find(f"{{{_SHEET_NS}}}cols")
    if cols_el is not None:
        for col_el in cols_el.iter(f"{{{_SHEET_NS}}}col"):
            if (col_el.get("hidden") or "") not in ("1", "true"):
                continue
            try:
                first = int(col_el.get("min") or 1)
                last = int(col_el.get("max") or first)
            except ValueError:
                continue
            for column in range(first, min(last, first + 4096) + 1):
                hidden_columns.add(column)

    merge_el = root.find(f"{{{_SHEET_NS}}}mergeCells")
    if merge_el is not None:
        for merge in merge_el.iter(f"{{{_SHEET_NS}}}mergeCell"):
            parsed = parse_range(merge.get("ref") or "")
            if parsed is not None:
                merged.append(parsed)

    # Tables formales viven en las rels de la hoja.
    sheet_dir = path.rsplit("/", 1)[0]
    sheet_file = path.rsplit("/", 1)[-1]
    rels_path = f"{sheet_dir}/_rels/{sheet_file}.rels"
    rels_xml = _read_member(archive, rels_path, 4 * 1024 * 1024)
    if rels_xml is not None:
        for target in _read_relationships(rels_xml, _PKG_REL_NS).values():
            table_path = _normalize_target(
                target if target.startswith("/") else f"{sheet_dir}/{target}"
            )
            table_xml = _read_member(archive, table_path, 8 * 1024 * 1024)
            if table_xml is None:
                continue
            table = _parse_table_meta(table_xml)
            if table is not None:
                excel_tables.append(table)

    return SheetMeta(
        name=name,
        path=path,
        state=state,
        dimension=dimension,
        merged=tuple(merged),
        hidden_rows=frozenset(hidden_rows),
        hidden_columns=frozenset(hidden_columns),
        excel_tables=tuple(excel_tables),
        formula_count=formula_count,
        truncated=truncated,
    )


def _parse_table_meta(table_xml: bytes) -> TableMeta | None:
    try:
        root = ElementTree.fromstring(table_xml)  # noqa: S314 (bytes acotados por presupuesto anti zip-bomb)
    except ElementTree.ParseError:
        return None
    name = root.get("displayName") or root.get("name") or ""
    if not name:
        return None
    columns = tuple(
        column.get("name") or "" for column in root.iter(f"{{{_SHEET_NS}}}tableColumn")
    )
    return TableMeta(
        name=name,
        ref=parse_range(root.get("ref") or ""),
        header_row_count=int(root.get("headerRowCount") or 1),
        totals_row_count=int(root.get("totalsRowCount") or 0),
        columns=columns,
    )

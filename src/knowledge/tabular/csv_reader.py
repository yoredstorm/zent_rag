# =============================================================================
# Tabular ingestion — lectura CSV robusta (encoding + dialecto)
# =============================================================================
# Detecta encoding (BOM, UTF-8, CP1252, Latin-1), delimitador (, ; | \t),
# quotechar y estilo decimal sin dependencias externas. Entrega un SheetGrid
# (una hoja = una tabla) con límites duros de filas/columnas/celdas.
# =============================================================================
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field

from src.knowledge.tabular.grid import SheetGrid

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_DELIMITERS = ",;\t|"
_SNIFF_SAMPLE = 64 * 1024


@dataclass(frozen=True, kw_only=True)
class CsvDialectInfo:
    encoding: str = "utf-8"
    has_bom: bool = False
    delimiter: str = ","
    quotechar: str = '"'
    decimal_style: str = "dot"  # dot | comma | unknown
    newline_style: str = "lf"  # lf | crlf | mixed
    metadata: dict = field(default_factory=dict)


class CsvReadError(ValueError):
    """CSV ilegible o vacío."""


def decode_csv(data: bytes) -> tuple[str, str, bool]:
    """Devuelve (texto, encoding, tenía_bom). Fallback seguro a latin-1."""
    import codecs

    for encoding in _ENCODINGS:
        try:
            text = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        has_bom = text.startswith("\ufeff") or data.startswith(codecs.BOM_UTF8)
        return text.lstrip("\ufeff"), encoding, has_bom
    # latin-1 nunca falla; esta línea es defensiva.
    raise CsvReadError("CSV could not be decoded")  # pragma: no cover


def sniff_dialect(text: str, *, configured_delimiter: str | None = None) -> tuple[str, str]:
    """(delimiter, quotechar) — configuración explícita > csv.Sniffer > conteo."""
    if configured_delimiter:
        return configured_delimiter[:1], '"'
    sample = text[:_SNIFF_SAMPLE]
    if sample.strip():
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=_DELIMITERS)
            if dialect.delimiter in _DELIMITERS:
                return dialect.delimiter, dialect.quotechar or '"'
        except csv.Error:
            pass
    # Fallback: el delimitador con más ocurrencias consistentes en las líneas.
    lines = [ln for ln in sample.splitlines() if ln.strip()][:20]
    best_delimiter, best_score = ",", -1.0
    for candidate in _DELIMITERS:
        counts = [ln.count(candidate) for ln in lines]
        if not counts:
            continue
        positive = [c for c in counts if c > 0]
        if not positive:
            continue
        consistency = 1.0 - (
            (max(positive) - min(positive)) / max(max(positive), 1)
        )
        score = sum(positive) * consistency
        if score > best_score:
            best_delimiter, best_score = candidate, score
    return best_delimiter, '"'


def detect_decimal_style(text: str, delimiter: str) -> str:
    """Heurística barata: '1.234,56' (comma) vs '1,234.56' (dot).

    Con delimitador coma, una coma no puede ser separador decimal fuera de
    comillas: se revisan primero los campos entrecomillados.
    """
    sample = text[:200_000]
    quoted = " ".join(re.findall(r'"([^"]*)"', sample))
    dot_decimal = len(re.findall(r"\d\.\d{1,2}\b", sample))
    if delimiter == ",":
        comma_decimal = len(re.findall(r"\d,\d{1,2}\b", quoted))
        return "comma" if comma_decimal > dot_decimal else "dot"
    comma_decimal = len(re.findall(r"\d,\d{1,2}\b", sample))
    if comma_decimal > dot_decimal:
        return "comma"
    if dot_decimal > comma_decimal:
        return "dot"
    return "unknown"


def detect_newline_style(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    return "lf"


def read_csv_grid(
    data: bytes,
    filename: str,
    *,
    max_rows: int = 100_000,
    max_columns: int = 512,
    max_cells: int = 2_000_000,
    sheet_name: str | None = None,
    configured_delimiter: str | None = None,
    configured_encoding: str | None = None,
) -> tuple[SheetGrid, CsvDialectInfo]:
    """Lee un CSV completo a SheetGrid con dialecto detectado y límites duros."""
    if not data.strip():
        raise CsvReadError(f"CSV is empty: {filename}")

    if configured_encoding:
        try:
            text = data.decode(configured_encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            raise CsvReadError(
                f"CSV could not be decoded with {configured_encoding}: {exc}"
            ) from exc
        has_bom = text.startswith("\ufeff")
        text = text.lstrip("\ufeff")
        encoding = configured_encoding
    else:
        text, encoding, has_bom = decode_csv(data)

    delimiter, quotechar = sniff_dialect(text, configured_delimiter=configured_delimiter)
    decimal_style = detect_decimal_style(text, delimiter)
    newline_style = detect_newline_style(data)

    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quotechar=quotechar)
    raw_rows: list[list[str]] = []
    row_lengths: list[int] = []
    truncated = False
    limits_hit: list[str] = []
    cell_count = 0
    max_seen_columns = 0
    for index, row in enumerate(reader):
        if index >= max_rows:
            truncated = True
            limits_hit.append("max_rows_per_sheet")
            break
        values = [str(value) for value in row]
        row_lengths.append(len(values))
        if len(values) > max_columns:
            values = values[:max_columns]
            if "max_columns" not in limits_hit:
                limits_hit.append("max_columns")
            truncated = True
        max_seen_columns = max(max_seen_columns, len(values))
        cell_count += len(values)
        if cell_count > max_cells:
            truncated = True
            limits_hit.append("max_cells")
            break
        raw_rows.append(values)

    if not raw_rows:
        raise CsvReadError(f"CSV has no rows: {filename}")

    min_col, max_col = 1, max_seen_columns
    rows: list[tuple[int, tuple[str, ...]]] = []
    for index, values in enumerate(raw_rows, start=1):
        padded = tuple(values) + ("",) * (max_col - len(values))
        if not any(value.strip() for value in padded):
            continue
        rows.append((index, tuple(value if value is not None else "" for value in padded)))

    grid = SheetGrid(
        name=sheet_name or _sheet_name_from_filename(filename),
        index=0,
        min_col=min_col,
        max_col=max_col,
        rows=tuple(rows),
        truncated=truncated,
        limits_hit=tuple(limits_hit),
        metadata={
            "csv": True,
            "ragged_rows": sum(
                1
                for length in row_lengths
                if 0 < length < max_seen_columns
            ),
        },
    )
    info = CsvDialectInfo(
        encoding=encoding,
        has_bom=has_bom,
        delimiter=delimiter,
        quotechar=quotechar,
        decimal_style=decimal_style,
        newline_style=newline_style,
        metadata={"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()},
    )
    return grid, info


def _sheet_name_from_filename(filename: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", filename or "").strip()
    return stem[:80] or "data"


def build_csv_workbook_grid(
    data: bytes,
    filename: str,
    *,
    max_rows: int = 100_000,
    max_columns: int = 512,
    max_cells: int = 2_000_000,
    configured_delimiter: str | None = None,
    configured_encoding: str | None = None,
) -> tuple:
    """CSV → (WorkbookGrid, CsvDialectInfo) con hash y dialecto en metadata."""
    from src.knowledge.tabular.grid import WorkbookGrid

    grid, dialect = read_csv_grid(
        data,
        filename,
        max_rows=max_rows,
        max_columns=max_columns,
        max_cells=max_cells,
        configured_delimiter=configured_delimiter,
        configured_encoding=configured_encoding,
    )
    workbook_grid = WorkbookGrid(
        filename=filename,
        format="csv",
        sheets=(grid,),
        content_hash=hashlib.sha256(data).hexdigest(),
        source_bytes=len(data),
        truncated=grid.truncated,
        limits_hit=grid.limits_hit,
        metadata={
            "dialect": {
                "encoding": dialect.encoding,
                "has_bom": dialect.has_bom,
                "delimiter": dialect.delimiter,
                "quotechar": dialect.quotechar,
                "decimal_style": dialect.decimal_style,
                "newline_style": dialect.newline_style,
            }
        },
    )
    return workbook_grid, dialect

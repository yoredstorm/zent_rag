# =============================================================================
# Medición de consumo de embeddings — Excel/CSV (F0 del plan de supersede V1)
# =============================================================================
# Compara dos representaciones de un mismo archivo:
#   baseline  = V1 (una fila = un chunk) + tabular V2 actual (grupos capados a
#               `max_embedding_rows`, render verboso "Columna: valor").
#   proposed  = V1 resumen único + tabular V2 con grupos compactos cubriendo
#               TODAS las filas (render `fila: valor | valor`).
#
# El modo baseline se computa con renderers locales de medición (replican el
# comportamiento previo) para que el número sea reproducible aunque el pipeline
# evolucione. El modo proposed usa el código productivo.
#
# Uso:
#   python -m src.scripts.measure_tabular_embeddings <archivo.xlsx|csv> [--json]
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from src.knowledge.structure.base import token_count
from src.rag.chunking.registry import get_chunker

_EMBED_BATCH = 32  # mismo batch que el engine
_ORG = UUID("00000000-0000-0000-0000-0000000000aa")
_SOURCE = UUID("00000000-0000-0000-0000-0000000000bb")


def _load_workbook(path: Path):
    from src.knowledge.tabular.builder import build_tabular_workbook
    from src.knowledge.tabular.csv_reader import build_csv_workbook_grid
    from src.knowledge.tabular.xlsx_reader import read_xlsx_grid

    data = path.read_bytes()
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        grid = read_xlsx_grid(data, path.name)
    else:
        grid, _dialect = build_csv_workbook_grid(data, path.name)
    return build_tabular_workbook(
        grid,
        organization_id=_ORG,
        external_id=f"obj/{path.name}",
        source_id=_SOURCE,
        filename=path.name,
    )


def _summary_record_text(workbook) -> str:
    """Texto del record resumen V1 cuando supersede está activo."""
    lines = [
        f"Workbook: {workbook.filename}",
        f"Format: {workbook.format.value}",
        f"Sheets: {workbook.sheet_count} | Tables: {workbook.table_count} | "
        f"Rows: {workbook.row_count}",
    ]
    for sheet in workbook.sheets:
        lines.append(f"Sheet: {sheet.name} ({sheet.table_count} table(s))")
        for table in sheet.tables:
            columns = ", ".join(
                column.original_name or column.normalized_name
                for column in table.columns[:30]
            )
            lines.append(
                f"Table: {table.name} | columns: {columns} | rows: {table.row_count}"
            )
    return "\n".join(lines)


def _v1_row_texts(path: Path) -> list[str]:
    """Simula el camino V1 actual de Excel/CSV: un record por fila."""
    from src.knowledge.connectors.csv_source import rows_to_records
    from src.knowledge.tabular.xlsx_reader import read_xlsx_grid

    data = path.read_bytes()
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        grid = read_xlsx_grid(data, path.name)
        sheet = grid.sheets[0]
        values = list(sheet.rows)
        if not values:
            return []
        headers = [
            value.strip() or f"col_{index}"
            for index, value in enumerate(values[0][1])
        ]
        rows = [
            {headers[i]: cell for i, cell in enumerate(row) if i < len(headers)}
            for _number, row in values[1:]
        ]
    else:
        import csv
        import io

        text = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.DictReader(io.StringIO(text)))
    records = rows_to_records(rows, "obj", extra_metadata={})
    return [record.content for record in records]


def _verbose_row_group(table, rows) -> str:
    """Render previo (verboso) — solo para medir el baseline."""
    header_names = [
        column.original_name or column.normalized_name for column in table.columns
    ]
    lines = [
        f"TABLE: {table.name}",
        f"ROWS: {rows[0].physical_row}-{rows[-1].physical_row}",
        "COLUMNS: " + " | ".join(header_names),
        "ROWS:",
    ]
    for row in rows:
        cells = []
        for column in table.columns:
            value = row.value_for(column)
            if value == "":
                continue
            label = column.original_name or column.normalized_name
            cells.append(f"{label}: {value[:600]}")
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def measure_baseline(path: Path) -> dict:
    """Solo el baseline (V1 filas + V2 actual), sin depender de cambios futuros."""
    workbook = _load_workbook(path)
    v1_texts = _v1_row_texts(path)
    fixed = get_chunker("fixed", 1200, 150)
    v1_chunks: list[str] = []
    for text in v1_texts:
        v1_chunks.extend(fixed.chunk(text))
    baseline_v2 = _baseline_v2_texts(workbook)
    tokens = sum(token_count(text) for text in v1_chunks + baseline_v2)
    chunks = len(v1_chunks) + len(baseline_v2)
    return {
        "file": path.name,
        "rows": workbook.row_count,
        "columns": workbook.tables()[0].column_count if workbook.tables() else 0,
        "baseline": {
            "chunks": chunks,
            "v1_chunks": len(v1_chunks),
            "v2_chunks": len(baseline_v2),
            "tokens": tokens,
            "chars": sum(len(text) for text in v1_chunks + baseline_v2),
            "embed_requests": (chunks + _EMBED_BATCH - 1) // _EMBED_BATCH,
        },
    }


def _baseline_v2_texts(workbook) -> list[str]:
    groups = workbook.metadata.get("row_group_size") or 20
    overlap = workbook.metadata.get("row_group_overlap") or 2
    step = max(1, groups - overlap)
    from src.knowledge.tabular.limits import tabular_limits

    max_rows = int(tabular_limits().max_embedding_rows)
    texts: list[str] = []
    for table in workbook.tables():
        rows = table.rows[:max_rows]
        for start in range(0, len(rows), step):
            window = rows[start : start + groups]
            if window:
                texts.append(_verbose_row_group(table, window))
        for row in rows:
            texts.append(
                "\n".join(
                    [
                        f"Workbook: {workbook.filename}",
                        f"Sheet: {workbook.sheets[0].name}",
                        f"Table: {table.name}",
                        f"Row: {row.physical_row}",
                        *[
                            f"{column.original_name or column.normalized_name}: "
                            f"{row.value_for(column)}"
                            for column in table.columns
                            if row.value_for(column) != ""
                        ],
                    ]
                )
            )
        texts.append(
            "TABLE: " + table.name + "\nCOLUMNS: "
            + " | ".join(
                column.original_name or column.normalized_name
                for column in table.columns
            )
        )
    return texts


def measure(path: Path) -> dict:
    from src.knowledge.tabular.chunker import (
        TabularChunkingConfig,
        chunk_tabular_workbook,
    )
    from src.knowledge.tabular.document import document_id_for, tabular_document
    from src.knowledge.tabular.ids import TABULAR_NS

    workbook = _load_workbook(path)
    document = tabular_document(
        workbook,
        document_id=document_id_for(TABULAR_NS, _ORG, _SOURCE, f"obj/{path.name}"),
    )

    # --- baseline ---------------------------------------------------------
    v1_texts = _v1_row_texts(path)
    fixed = get_chunker("fixed", 1200, 150)
    v1_chunks: list[str] = []
    for text in v1_texts:
        v1_chunks.extend(fixed.chunk(text))

    baseline_v2: list[str] = _baseline_v2_texts(workbook)
    groups = workbook.metadata.get("row_group_size") or 20
    overlap = workbook.metadata.get("row_group_overlap") or 2
    from src.knowledge.tabular.limits import tabular_limits

    max_rows = int(tabular_limits().max_embedding_rows)

    # --- proposed (código productivo) --------------------------------------
    summary_text = _summary_record_text(workbook)
    proposed_v1_chunks = fixed.chunk(summary_text)
    proposed_chunks = chunk_tabular_workbook(
        document,
        config=TabularChunkingConfig(
            row_group_size=groups,
            row_group_overlap=overlap,
            max_embedding_rows_per_table=max_rows,
            max_group_rows=20_000,
        ),
    )

    def stats(texts: list[str]) -> dict:
        tokens = sum(token_count(text) for text in texts)
        chars = sum(len(text) for text in texts)
        requests = (len(texts) + _EMBED_BATCH - 1) // _EMBED_BATCH
        return {
            "chunks": len(texts),
            "tokens": tokens,
            "chars": chars,
            "embed_requests": requests,
        }

    baseline = stats(v1_chunks + baseline_v2)
    proposed_texts = proposed_v1_chunks + [chunk.content for chunk in proposed_chunks]
    proposed = stats(proposed_texts)
    return {
        "file": path.name,
        "rows": workbook.row_count,
        "tables": workbook.table_count,
        "columns": workbook.tables()[0].column_count if workbook.tables() else 0,
        "baseline": {
            **baseline,
            "v1_chunks": len(v1_chunks),
            "v2_chunks": len(baseline_v2),
        },
        "proposed": {
            **proposed,
            "v1_chunks": len(proposed_v1_chunks),
            "v2_chunks": len(proposed_chunks),
            "v2_levels": _levels(proposed_chunks),
        },
    }


def _levels(chunks) -> dict:
    levels: dict[str, int] = {}
    for chunk in chunks:
        key = str(chunk.metadata.get("level"))
        levels[key] = levels.get(key, 0) + 1
    return levels


def main() -> None:
    parser = argparse.ArgumentParser(description="Medición de embeddings tabulares")
    parser.add_argument("path", help="Archivo .xlsx/.csv a medir")
    parser.add_argument("--json", action="store_true", help="Salida JSON plana")
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Solo mide el baseline (útil antes de implementar el modo propuesto)",
    )
    args = parser.parse_args()

    if args.baseline_only:
        result = measure_baseline(Path(args.path))
        print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else result)
        return

    result = measure(Path(args.path))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    baseline, proposed = result["baseline"], result["proposed"]
    print(f"Archivo: {result['file']} | filas: {result['rows']} | "
          f"columnas: {result['columns']}")
    print(f"BASELINE  chunks={baseline['chunks']} "
          f"(V1={baseline['v1_chunks']} V2={baseline['v2_chunks']}) "
          f"tokens={baseline['tokens']} requests~{baseline['embed_requests']}")
    print(f"PROPUESTO chunks={proposed['chunks']} "
          f"(V1={proposed['v1_chunks']} V2={proposed['v2_chunks']} "
          f"niveles={proposed['v2_levels']}) "
          f"tokens={proposed['tokens']} requests~{proposed['embed_requests']}")
    if baseline["tokens"]:
        print(f"tokens: {proposed['tokens'] / baseline['tokens']:.1%} del baseline")
    if baseline["embed_requests"]:
        print(f"requests: {proposed['embed_requests'] / baseline['embed_requests']:.1%} del baseline")


if __name__ == "__main__":
    sys.exit(main())

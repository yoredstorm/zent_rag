# =============================================================================
# Tabular ingestion — paquete (Knowledge Tabular V2)
# =============================================================================
# Entrypoints:
#   build_tabular_workbook(WorkbookGrid, ...) -> TabularWorkbook
#   read_xlsx_grid(bytes, filename) / read_csv_grid(bytes, filename)
#   chunk_tabular_workbook(document, ...)     -> chunks semánticos (Qdrant)
#   diff_table_fingerprints(...)              -> cambios incrementales
# =============================================================================
from __future__ import annotations

from src.knowledge.tabular.builder import (
    TabularBuildLimits,
    build_tabular_workbook,
)
from src.knowledge.tabular.chunker import (
    TabularChunkingConfig,
    chunk_tabular_workbook,
)
from src.knowledge.tabular.csv_reader import CsvDialectInfo, CsvReadError, read_csv_grid
from src.knowledge.tabular.fingerprint import (
    TableDiff,
    compute_workbook_diff,
    diff_table,
    schema_changed,
    table_row_hashes,
    workbook_fingerprint,
)
from src.knowledge.tabular.grid import ExcelTableDef, SheetGrid, WorkbookGrid
from src.knowledge.tabular.lookup import TabularLookupResult, resolve_exact_lookup
from src.knowledge.tabular.map import (
    TabularMap,
    build_tabular_map,
    find_candidate_tables,
    render_tabular_map_text,
)
from src.knowledge.tabular.persistence import persist_tabular_workbook
from src.knowledge.tabular.query import TabularQueryService, classify_tabular_question
from src.knowledge.tabular.xlsx_reader import XlsxReadError, read_xlsx_grid

__all__ = [
    "CsvDialectInfo",
    "CsvReadError",
    "ExcelTableDef",
    "SheetGrid",
    "TabularBuildLimits",
    "TabularChunkingConfig",
    "TabularLookupResult",
    "TabularMap",
    "TabularQueryService",
    "TableDiff",
    "WorkbookGrid",
    "XlsxReadError",
    "build_tabular_map",
    "build_tabular_workbook",
    "chunk_tabular_workbook",
    "classify_tabular_question",
    "compute_workbook_diff",
    "diff_table",
    "find_candidate_tables",
    "persist_tabular_workbook",
    "read_csv_grid",
    "read_xlsx_grid",
    "render_tabular_map_text",
    "resolve_exact_lookup",
    "schema_changed",
    "table_row_hashes",
    "workbook_fingerprint",
]

# =============================================================================
# Tabular ingestion — límites configurables (RAG_KNOWLEDGE_TABULAR_*)
# =============================================================================
# Un solo lugar traduce Settings → TabularBuildLimits / parámetros de lectura.
# =============================================================================
from __future__ import annotations

from src.core.config import get_settings
from src.knowledge.tabular.builder import TabularBuildLimits


def tabular_limits() -> TabularBuildLimits:
    settings = get_settings()
    return TabularBuildLimits(
        max_sheets=int(settings.KNOWLEDGE_TABULAR_MAX_SHEETS),
        max_rows_per_sheet=int(settings.KNOWLEDGE_TABULAR_MAX_ROWS_PER_SHEET),
        max_columns=int(settings.KNOWLEDGE_TABULAR_MAX_COLUMNS),
        max_cells=int(settings.KNOWLEDGE_TABULAR_MAX_CELLS),
        max_embedding_rows=int(settings.KNOWLEDGE_TABULAR_MAX_EMBEDDING_ROWS),
        row_group_size=int(settings.KNOWLEDGE_TABULAR_ROW_GROUP_SIZE),
        row_group_overlap=int(settings.KNOWLEDGE_TABULAR_ROW_GROUP_OVERLAP),
    )


def tabular_enabled() -> bool:
    return bool(get_settings().KNOWLEDGE_TABULAR_ENABLED)

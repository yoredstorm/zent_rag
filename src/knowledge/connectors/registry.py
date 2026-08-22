# =============================================================================
# Source Registry — type -> conector
# =============================================================================
# Agregar una fuente nueva = registrar una clase nueva. El engine no cambia.
# =============================================================================
from __future__ import annotations

from src.core.domain.entities import KbSource
from src.knowledge.connectors.api_source import ApiSourceConnector
from src.knowledge.connectors.base import SourceConnector
from src.knowledge.connectors.csv_source import CSVSourceConnector
from src.knowledge.connectors.excel_source import ExcelSourceConnector
from src.knowledge.connectors.file_source import FileSourceConnector
from src.knowledge.connectors.s3_source import S3SourceConnector
from src.knowledge.connectors.sql_source import SQLSourceConnector
from src.knowledge.connectors.web_source import WebSourceConnector

_REGISTRY: dict[str, type[SourceConnector]] = {
    cls.source_type: cls
    for cls in (
        SQLSourceConnector,
        FileSourceConnector,
        CSVSourceConnector,
        ExcelSourceConnector,
        WebSourceConnector,
        S3SourceConnector,
        ApiSourceConnector,
    )
}


def register_connector(cls: type[SourceConnector]) -> None:
    _REGISTRY[cls.source_type] = cls


def source_types() -> list[str]:
    return sorted(_REGISTRY)


def build_connector(source: KbSource) -> SourceConnector:
    cls = _REGISTRY.get(source.type)
    if cls is None:
        raise ValueError(f"Unknown source type '{source.type}'. Available: {source_types()}")
    return cls(source)

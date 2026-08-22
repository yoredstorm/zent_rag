# =============================================================================
# Knowledge Platform — SourceConnector (interfaz común de fuentes)
# =============================================================================
# Toda fuente (sql, file, csv, excel, web, s3, api) implementa esta interfaz.
# El motor de ingestion solo conoce esta abstracción: nunca sabe de dominios
# verticales (farmacia, retail, ...).
#
# Dos modos de sync:
# - self_contained=True  (sql): el conector hace su propio pipeline interno
#   (serialización + embed + upsert) y retorna un SyncOutcome con métricas.
# - self_contained=False (resto): el conector entrega records normalizados a
#   Markdown vía iter_records(); el engine aplica chunking/embed/upsert
#   según la configuración de la Knowledge Base.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from src.core.domain.entities import KbSource


class ConnectorError(Exception):
    """Error de conexión/validación de una fuente."""


@dataclass(kw_only=True, frozen=True)
class Record:
    """Registro normalizado (Markdown) listo para chunking."""

    external_id: str
    content: str
    metadata: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class SyncOutcome:
    """Resultado de un sync self-contained (ej. SQL)."""

    records_processed: int = 0
    records_failed: int = 0
    cursor: dict | None = None
    seen_external_ids: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


@dataclass(kw_only=True, frozen=True)
class DiscoveredItem:
    """Elemento descubierto por una fuente (preview para la UI)."""

    external_id: str
    label: str
    extra: dict = field(default_factory=dict)


class SourceConnector(ABC):
    """Interfaz común de conectores de ingestion."""

    source_type: ClassVar[str] = "unknown"
    self_contained: ClassVar[bool] = False

    def __init__(self, source: KbSource) -> None:
        self.source = source

    @property
    def config(self) -> dict:
        return self.source.config_json or {}

    async def connect(self) -> None:
        """Establece la conexión (levanta ConnectorError si no es posible)."""
        return None

    @abstractmethod
    async def validate(self) -> None:
        """Valida configuración y conectividad. Levanta ConnectorError."""

    async def discover(self) -> list[DiscoveredItem]:
        """Lista elementos disponibles (tablas, objetos, endpoints...)."""
        return []

    async def sync(self, cursor: dict | None) -> SyncOutcome:
        """Sync self-contained (usa cursor incremental)."""
        raise ConnectorError(
            f"Connector '{self.source_type}' does not support self-contained sync"
        )

    async def iter_records(self, cursor: dict | None):
        """Yield de Records normalizados (modo engine-driven)."""
        raise ConnectorError(
            f"Connector '{self.source_type}' does not support record iteration"
        )
        yield  # pragma: no cover

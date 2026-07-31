# =============================================================================
# Domain Service Contracts — Servicios de Negocio (Clean Architecture)
# =============================================================================
# Define contratos abstractos para servicios de dominio que orquestan
# múltiples puertos. Separados de entities/ports porque representan
# lógica de negocio compuesta, no simples operaciones CRUD.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class DataSource:
    """Representa una tabla o fuente de datos descubierta dinámicamente."""

    schema_name: str
    table_name: str
    columns: list[ColumnMeta] = field(default_factory=list)
    row_count: int = 0
    is_view: bool = False
    is_discovered: bool = True  # True = automático, False = configurado manualmente


@dataclass
class ColumnMeta:
    """Metadatos de una columna."""

    name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool = False
    is_foreign_key: bool = False
    fk_table: str | None = None
    fk_column: str | None = None


@dataclass
class IngestionResult:
    """Resultado de una operación de ingesta."""

    tenant_id: UUID
    tables_processed: int
    rows_indexed: int = 0
    vectors_upserted: int = 0
    errors: list[str] = field(default_factory=list)
    failed_rows: int = 0
    duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class IngestionService(ABC):
    """Contrato para el servicio de ingesta de datos → vector store.

    Descubre automáticamente tablas en la BD relacional, serializa cada fila
    en texto enriquecido (NL), genera embeddings y los indexa en Qdrant
    con metadatos completos para filtrado semántico.

    Funciona para cualquier dominio (retail, farmacia, cafetería) sin
    cambios de código gracias al discovery automático de esquema.
    """

    @abstractmethod
    async def discover_sources(self, tenant_id: UUID) -> list[DataSource]:
        """Descubre todas las tablas disponibles para un tenant."""
        ...

    @abstractmethod
    async def sync_all(self, tenant_id: UUID, full_refresh: bool = False) -> IngestionResult:
        """Sincroniza todas las tablas descubiertas con la BD vectorial."""
        ...

    @abstractmethod
    async def sync_table(
        self, tenant_id: UUID, schema_name: str, table_name: str, full_refresh: bool = False
    ) -> IngestionResult:
        """Sincroniza una tabla específica."""
        ...

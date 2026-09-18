# =============================================================================
# Ports — Tabular repository (Knowledge Tabular V2)
# =============================================================================
# Persiste el árbol TabularWorkbook (workbooks/sheets/tables/columns/rows) con
# el MISMO contrato de aislamiento que el resto de la plataforma:
# organization_id es OBLIGATORIO en toda operación; ninguna consulta puede
# devolver filas de otra organización.
#
# Separación de responsabilidades:
#   - el repositorio expone `get_fingerprint` (estado persistido) y
#     `upsert_workbook(workbook, diff)` (persiste SOLO lo que el diff indica);
#   - el cálculo del diff (schema/row hashes) vive en la capa knowledge
#     (`src/knowledge/tabular/fingerprint.py`) → nada de lógica de fingerprint
#     en SQL.
# =============================================================================
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from src.core.domain.tabular import (
    TabularFingerprint,
    TabularWorkbook,
    WorkbookDiff,
)


class TabularRepository(ABC):
    """Puerto de persistencia estructurada de workbooks tabulares."""

    @abstractmethod
    async def get_fingerprint(
        self, organization_id: UUID, workbook_id: UUID
    ) -> TabularFingerprint | None:
        """Estado persistido (content_hash + schema/row hashes) o None."""
        ...

    @abstractmethod
    async def upsert_workbook(
        self,
        workbook: TabularWorkbook,
        diff: WorkbookDiff,
        *,
        knowledge_base_id: UUID | None = None,
    ) -> None:
        """Persiste el workbook aplicando el diff (incremental)."""
        ...

    @abstractmethod
    async def get_workbook(
        self, organization_id: UUID, source_id: UUID, external_id: str
    ) -> dict | None:
        """Metadata del workbook (incluye profile/quality) o None. Scoped."""
        ...

    @abstractmethod
    async def list_workbooks(
        self, organization_id: UUID, source_id: UUID
    ) -> list[dict]:
        """Workbooks de una fuente (resumen para UI/observabilidad). Scoped."""
        ...

    @abstractmethod
    async def list_tables(
        self,
        organization_id: UUID,
        source_id: UUID | None = None,
        *,
        workbook_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> list[dict]:
        """Tablas (schema-level) del tenant, filtrables por fuente/workbook/KB."""
        ...

    @abstractmethod
    async def list_columns(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        workbook_id: UUID | None = None,
        knowledge_base_id: UUID | None = None,
    ) -> list[dict]:
        """Columnas de todas las tablas del scope (para el mapa tabular)."""
        ...

    @abstractmethod
    async def get_table(self, organization_id: UUID, table_id: UUID) -> dict | None:
        """Tabla + columnas de una tabla (scoped)."""
        ...

    @abstractmethod
    async def fetch_rows(
        self,
        organization_id: UUID,
        table_id: UUID,
        *,
        filters: dict[str, str] | None = None,
        range_filters: list[tuple[str, str, str]] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """Filas por igualdad y/o rango numérico sobre columnas (valores exactos).

        `range_filters`: [(columna_normalizada, operador, valor)] con operador
        en {">", ">=", "<", "<=", "=", "!="}; el valor se castea a numeric en SQL.
        """
        ...

    @abstractmethod
    async def count_rows(
        self,
        organization_id: UUID,
        table_id: UUID,
        *,
        filters: dict[str, str] | None = None,
        range_filters: list[tuple[str, str, str]] | None = None,
    ) -> int:
        """COUNT(*) con los mismos filtros que `fetch_rows` (agregaciones)."""
        ...

    @abstractmethod
    async def sample_values(
        self,
        organization_id: UUID,
        table_id: UUID,
        column_id: UUID,
        limit: int = 20,
    ) -> list[str]:
        """Valores distintos (raw) de una columna — índice ligero de valores."""
        ...

    @abstractmethod
    async def list_relations(
        self,
        organization_id: UUID,
        *,
        source_id: UUID | None = None,
        workbook_id: UUID | None = None,
    ) -> list[dict]:
        """Relaciones candidatas (join/lookup/hierarchy) del scope (para UI/router)."""
        ...

    async def set_representations(
        self,
        organization_id: UUID,
        workbook_id: UUID,
        representations: dict,
    ) -> None:
        """Marca qué representaciones quedaron indexadas (UI/observabilidad).

        Default sin soporte; el adaptador Postgres actualiza metadata.
        """
        return None

    async def set_runtime_metadata(
        self,
        organization_id: UUID,
        workbook_id: UUID,
        values: dict,
    ) -> None:
        """Fusiona metadata de runtime (p. ej. chunking_policy) en el workbook.

        Default sin soporte; el adaptador Postgres actualiza metadata.
        """
        return None

    @abstractmethod
    async def delete_for_source(self, organization_id: UUID, source_id: UUID) -> None:
        """Elimina workbooks/árbol de la fuente (scoped, cascade)."""
        ...

    async def delete_missing_workbooks(
        self,
        organization_id: UUID,
        source_id: UUID,
        keep_external_ids: set[str],
    ) -> int:
        """Elimina workbooks cuyo external_id ya no existe en el sync actual."""
        return 0

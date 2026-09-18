# =============================================================================
# Tabular ingestion — identidad determinista de nodos
# =============================================================================
# Todos los IDs del árbol tabular son uuid5 sobre (organización, fuente,
# external_id, ubicación física). Re-ingestar el mismo archivo produce los
# mismos IDs → upsert idempotente y diffs incrementales estables.
# =============================================================================
from __future__ import annotations

from uuid import UUID, uuid5

TABULAR_NS = UUID("e5b7c2a1-6d4f-4a8b-9c3e-7f1d2a6b8c50")

# Namespace para point keys de Qdrant de chunks tabulares (separado del
# namespace V2 para no colisionar con chunks de documentos).
TABULAR_POINT_NS = UUID("f2a9d4c7-8e31-4b6a-9f5d-1c7e3a2b6d80")


def normalize_external_id(value: str) -> str:
    return (value or "").strip()


def workbook_id(organization_id: UUID, source_id: UUID | None, external_id: str) -> UUID:
    return uuid5(
        TABULAR_NS,
        f"wb:{organization_id}:{source_id or ''}:{normalize_external_id(external_id)}",
    )


def sheet_id(workbook_id_value: UUID, index: int, name: str) -> UUID:
    return uuid5(TABULAR_NS, f"ws:{workbook_id_value}:{index}:{name.strip().lower()}")


def table_id(
    workbook_id_value: UUID,
    sheet_id_value: UUID,
    table_index: int,
    name: str,
) -> UUID:
    return uuid5(
        TABULAR_NS,
        f"tb:{workbook_id_value}:{sheet_id_value}:{table_index}:{name.strip().lower()}",
    )


def column_id(table_id_value: UUID, physical_column: int) -> UUID:
    return uuid5(TABULAR_NS, f"col:{table_id_value}:{physical_column}")


def row_id(table_id_value: UUID, physical_row: int) -> UUID:
    return uuid5(TABULAR_NS, f"row:{table_id_value}:{physical_row}")


def relation_id(workbook_id_value: UUID, from_column_id: UUID, to_column_id: UUID, kind: str) -> UUID:
    return uuid5(
        TABULAR_NS,
        f"rel:{workbook_id_value}:{from_column_id}:{to_column_id}:{kind}",
    )


def row_point_key(
    source_id: UUID | None,
    external_id: str,
    table_id_value: UUID,
    physical_row: int,
) -> str:
    """Clave determinista del punto Qdrant de una fila (incremental)."""
    return f"tab:v1:{source_id or ''}:{external_id}:{table_id_value}:row:{physical_row}"


def table_point_key(
    source_id: UUID | None,
    external_id: str,
    table_id_value: UUID,
    level: str,
    discriminator: str = "",
) -> str:
    """Clave determinista para chunks de nivel tabla/hoja/workbook."""
    suffix = f":{discriminator}" if discriminator else ""
    return (
        f"tab:v1:{source_id or ''}:{external_id}:{table_id_value}:{level}{suffix}"
    )


def point_id_for(key: str) -> UUID:
    return uuid5(TABULAR_POINT_NS, key)

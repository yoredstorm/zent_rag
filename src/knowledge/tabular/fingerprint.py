# =============================================================================
# Tabular ingestion — fingerprinting e incrementalidad (brief §12)
# =============================================================================
# workbook hash (bytes), schema hash por tabla y row hashes permiten detectar
# unchanged / inserted / updated / deleted / schema_changed sin re-embeder todo.
# El cálculo del diff vive aquí (capa knowledge); el repositorio solo persiste
# lo que el diff indique.
# =============================================================================
from __future__ import annotations

import hashlib

from src.core.domain.tabular import (
    TableDiff,
    TableFingerprint,
    TabularChangeKind,
    TabularFingerprint,
    TabularTable,
    TabularWorkbook,
    WorkbookDiff,
)

__all__ = [
    "TableDiff",
    "WorkbookDiff",
    "compute_workbook_diff",
    "diff_table",
    "schema_changed",
    "table_row_hashes",
    "workbook_fingerprint",
]


def workbook_fingerprint(data: bytes) -> str:
    """sha256 de los bytes del archivo fuente (gobierna el skip total)."""
    return hashlib.sha256(data).hexdigest()


def table_row_hashes(table: TabularTable) -> dict[int, str]:
    """{physical_row: content_hash} de una tabla (persistible en Postgres)."""
    return {row.physical_row: row.content_hash for row in table.rows}


def schema_changed(previous_schema_hash: str | None, table: TabularTable) -> bool:
    if not previous_schema_hash:
        return True
    return previous_schema_hash != table.schema_hash


def diff_table(
    table: TabularTable,
    previous_hashes: dict[int, str],
    *,
    previous_schema_hash: str | None = None,
) -> TableDiff:
    """Diff fila a fila contra los hashes persistidos de la misma tabla."""
    schema_differs = previous_schema_hash is None or schema_changed(
        previous_schema_hash, table
    )
    current = table_row_hashes(table)
    inserted = sorted(row for row in current if row not in previous_hashes)
    updated = sorted(
        row
        for row in current
        if row in previous_hashes and previous_hashes[row] != current[row]
    )
    deleted = sorted(row for row in previous_hashes if row not in current)
    unchanged = len(current) - len(inserted) - len(updated)

    if previous_schema_hash is None:
        change_kind = TabularChangeKind.CREATED
    elif schema_differs:
        change_kind = TabularChangeKind.SCHEMA_CHANGED
    elif inserted or updated or deleted:
        change_kind = TabularChangeKind.UPDATED
    else:
        change_kind = TabularChangeKind.UNCHANGED

    return TableDiff(
        table_id=table.id,
        change_kind=change_kind,
        schema_changed=schema_differs,
        inserted=len(inserted),
        updated=len(updated),
        deleted=len(deleted),
        unchanged=max(0, unchanged),
        inserted_rows=tuple(inserted),
        updated_rows=tuple(updated),
        deleted_rows=tuple(deleted),
        metadata={
            "current_rows": len(current),
            "previous_rows": len(previous_hashes),
        },
    )


def compute_workbook_diff(
    workbook: TabularWorkbook,
    fingerprint: TabularFingerprint | None,
) -> WorkbookDiff:
    """Compara el workbook nuevo contra el fingerprint persistido.

    - Sin fingerprint → todo CREATED.
    - Mismo content_hash y sin drift de filas → UNCHANGED (skip total).
    - Tablas presentes: diff por schema/rows.
    - Tablas ausentes: deleted_table_ids.
    """
    if fingerprint is None:
        diffs = tuple(
            diff_table(table, {}, previous_schema_hash=None)
            for table in workbook.tables()
        )
        return WorkbookDiff(
            workbook_id=workbook.id,
            change_kind=TabularChangeKind.CREATED,
            table_diffs=diffs,
            metadata={"fingerprint": "none"},
        )

    diffs = []
    for table in workbook.tables():
        previous = fingerprint.tables.get(table.id)
        diffs.append(
            diff_table(
                table,
                previous.row_hashes if previous else {},
                previous_schema_hash=previous.schema_hash if previous else None,
            )
        )
    current_ids = {table.id for table in workbook.tables()}
    deleted_table_ids = tuple(
        table_id for table_id in fingerprint.tables if table_id not in current_ids
    )

    current_pipeline_version = str(workbook.metadata.get("pipeline_version") or "")
    version_changed = bool(
        fingerprint.pipeline_version
        and current_pipeline_version
        and fingerprint.pipeline_version != current_pipeline_version
    )

    if (
        fingerprint.content_hash == workbook.content_hash
        and not deleted_table_ids
        and not version_changed
        and all(diff.change_kind is TabularChangeKind.UNCHANGED for diff in diffs)
    ):
        return WorkbookDiff(
            workbook_id=workbook.id,
            change_kind=TabularChangeKind.UNCHANGED,
            table_diffs=tuple(diffs),
            metadata={"fingerprint": "workbook_content_hash"},
        )

    return WorkbookDiff(
        workbook_id=workbook.id,
        change_kind=TabularChangeKind.UPDATED,
        table_diffs=tuple(diffs),
        deleted_table_ids=deleted_table_ids,
        metadata={
            "rows": {
                "inserted": sum(diff.inserted for diff in diffs),
                "updated": sum(diff.updated for diff in diffs),
                "deleted": sum(diff.deleted for diff in diffs),
            },
            "pipeline_version": current_pipeline_version,
            "pipeline_upgraded": version_changed,
        },
    )


def fingerprint_from_rows(
    workbook_id,
    content_hash: str | None,
    table_rows: dict,
) -> TabularFingerprint:
    """Construye el fingerprint desde filas crudas del repositorio.

    `table_rows`: {table_id: (schema_hash, {physical_row: content_hash})}.
    """
    tables = {
        table_id: TableFingerprint(
            table_id=table_id, schema_hash=schema_hash, row_hashes=row_hashes
        )
        for table_id, (schema_hash, row_hashes) in table_rows.items()
    }
    return TabularFingerprint(
        workbook_id=workbook_id, content_hash=content_hash, tables=tables
    )

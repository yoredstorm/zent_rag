# =============================================================================
# Tabular ingestion — materialización opcional en Managed Database (§11)
# =============================================================================
# Reutiliza src/platform/managed_db (proposals + run_schema_admin_sql) para
# crear una tabla física con provenance _zent_* y volcar las filas exactas.
#
# Es OPCIONAL y best-effort: solo corre con RAG_KNOWLEDGE_TABULAR_MANAGED_DB_ENABLED
#=true y si el workspace ya tiene Managed Database. La representación canónica
# sigue siendo tabular_* en la plataforma; esto habilita SQL/joins directos.
# =============================================================================
from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from src.core.domain.tabular import TabularTable, TabularValueType
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

PROVENANCE_COLUMNS = (
    "_zent_source_id",
    "_zent_workbook",
    "_zent_sheet",
    "_zent_table_id",
    "_zent_source_row",
)

_FRIENDLY_BY_TYPE: dict[TabularValueType, str] = {
    TabularValueType.INTEGER: "Integer",
    TabularValueType.FLOAT: "Number",
    TabularValueType.DECIMAL: "Number",
    TabularValueType.CURRENCY: "Money",
    TabularValueType.PERCENTAGE: "Number",
    TabularValueType.BOOLEAN: "Boolean",
    TabularValueType.DATE: "Date",
    TabularValueType.DATETIME: "Date & Time",
    TabularValueType.TIME: "Text",
}

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
# "ATPCO_Attributes table 1:1-24" → "ATPCO_Attributes" (el rango no aporta al
# nombre SQL; se re-agrega solo si hay colisión de nombres en el workbook).
_RANGE_SUFFIX_RE = re.compile(
    r"\s+table\s+\d+:\d+(?:-\d+(?::\d+)?)?\s*$", re.IGNORECASE
)


def base_table_name(table: TabularTable) -> str:
    """Nombre de tabla sin el sufijo de rango del detector."""
    name = (table.name or "").strip()
    cleaned = _RANGE_SUFFIX_RE.sub("", name).strip()
    return cleaned or name or "table"


@dataclass(frozen=True, kw_only=True)
class MaterializationResult:
    status: str  # applied | skipped | error
    table_name: str | None = None
    rows_written: int = 0
    detail: str = ""


def table_proposal(
    table: TabularTable, *, prefix: str = "zent", table_name: str | None = None
) -> dict:
    """TabularTable → proposal del managed_db (mismo contrato que el importer).

    Incluye columnas de provenance para no perder la relación con el archivo.
    """
    from src.platform.managed_db.builder import FRIENDLY_TYPES

    base_name = table_name or base_table_name(table)
    fields: list[dict] = []
    used: set[str] = set()
    for column in table.columns:
        name = _sanitize(column.normalized_name or f"column_{column.physical_column}")
        if name in used or name in PROVENANCE_COLUMNS:
            name = f"{name}_{column.excel_letter.lower()}"
        used.add(name)
        friendly = _FRIENDLY_BY_TYPE.get(column.inferred_type, "Text")
        if friendly not in FRIENDLY_TYPES:
            friendly = "Text"
        fields.append(
            {
                "name": name,
                "type": friendly,
                "unique": bool(
                    column.unique_ratio >= 0.95
                    and column.semantic_type.value in ("identifier", "code")
                ),
            }
        )
    for provenance in PROVENANCE_COLUMNS:
        fields.append({"name": provenance, "type": "Text", "unique": False})
    return {
        "tables": [
            {
                "name": _sanitize(f"{prefix}_{base_name}") or "zent_table",
                "fields": fields,
            }
        ],
        "relationships": [],
    }


def insert_rows_sql(
    table_name: str,
    columns: list[dict],
    rows: list[tuple[str, ...]],
    *,
    source_id: str,
    workbook: str,
    sheet: str,
    table_id: str,
    physical_rows: list[int],
) -> str:
    """INSERT con valores literales escapados (sin params multi-statement).

    Los valores vienen del parser determinista: nunca se ejecuta nada; solo se
    escapan comillas y se castean números/fechas a NULL cuando están vacíos.
    """
    from src.platform.managed_db.builder import _ident

    table = _ident(table_name)
    names = [_ident(column["name"]) for column in columns] + list(PROVENANCE_COLUMNS)
    cols = ", ".join(f'"{name}"' for name in names)
    values: list[str] = []
    for row, physical_row in zip(rows, physical_rows):
        rendered = [
            _render_value(row[index] if index < len(row) else "", columns[index]["type"])
            for index in range(len(columns))
        ]
        rendered.extend(
            [
                _quote(source_id),
                _quote(workbook),
                _quote(sheet),
                _quote(table_id),
                str(int(physical_row)),
            ]
        )
        values.append("(" + ", ".join(rendered) + ")")
    return f'INSERT INTO "{table}" ({cols}) VALUES ' + ", ".join(values)  # noqa: S608 (identificadores sanitizados por _ident, literales escapados)


async def materialize_table(
    table: TabularTable,
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    workbook_name: str,
    sheet_name: str,
    source_id: UUID | None,
    table_name: str | None = None,
    batch_size: int = 500,
) -> MaterializationResult:
    """Crea/actualiza la tabla física en la Managed Database y vuelca filas."""
    from src.platform.managed_db.builder import to_ddl
    from src.platform.managed_db.service import (
        get_managed_database,
        run_schema_admin_sql,
    )

    managed = await get_managed_database(organization_id, workspace_id)
    if not managed:
        return MaterializationResult(status="skipped", detail="managed_db_not_provisioned")

    proposal = table_proposal(table, table_name=table_name)
    proposal_table = proposal["tables"][0]
    table_name = proposal_table["name"]
    try:
        await run_schema_admin_sql(
            organization_id, workspace_id, to_ddl(proposal)
        )
        written = 0
        all_rows = [tuple(row.values) for row in table.rows]
        physical_rows = [row.physical_row for row in table.rows]
        for start in range(0, len(all_rows), batch_size):
            sql = insert_rows_sql(
                table_name,
                proposal_table["fields"][: len(table.columns)],
                all_rows[start : start + batch_size],
                source_id=str(source_id) if source_id else "",
                workbook=workbook_name,
                sheet=sheet_name,
                table_id=str(table.id),
                physical_rows=physical_rows[start : start + batch_size],
            )
            await run_schema_admin_sql(organization_id, workspace_id, sql)
            written += len(all_rows[start : start + batch_size])
        return MaterializationResult(
            status="applied", table_name=table_name, rows_written=written
        )
    except Exception as exc:  # noqa: BLE001 - materialización best-effort
        logger.warning(
            "Tabular managed-db materialization failed",
            table_id=str(table.id),
            error=str(exc)[:300],
        )
        return MaterializationResult(status="error", detail=str(exc)[:300])


async def materialize_tables(
    tables: list[tuple[TabularTable, str, str]],
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    source_id: UUID | None,
) -> list[MaterializationResult]:
    """Materializa una lista de (tabla, workbook, sheet).

    Si dos tablas del mismo workbook comparten nombre base (el detector agrega
    el rango), se re-agrega el rango a partir de la segunda para no pisarlas.
    """
    base_counts: dict[str, int] = {}
    for table, _workbook_name, _sheet_name in tables:
        base = base_table_name(table)
        base_counts[base] = base_counts.get(base, 0) + 1
    seen: dict[str, int] = {}
    results: list[MaterializationResult] = []
    for table, workbook_name, sheet_name in tables:
        base = base_table_name(table)
        override: str | None = None
        if base_counts[base] > 1:
            seen[base] = seen.get(base, 0) + 1
            if seen[base] > 1:
                cell_range = table.range
                override = (
                    f"{base} {cell_range.min_row}:{cell_range.min_col}"
                    f"-{cell_range.max_row}:{cell_range.max_col}"
                )
        results.append(
            await materialize_table(
                table,
                organization_id=organization_id,
                workspace_id=workspace_id,
                workbook_name=workbook_name,
                sheet_name=sheet_name,
                source_id=source_id,
                table_name=override,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z_]+", "_", (value or "").strip().lower()).strip("_")
    return cleaned[:48]


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _render_value(value: str, friendly_type: str) -> str:
    text = "" if value is None else str(value)
    if text == "":
        return "NULL"
    if friendly_type in ("Integer", "Number", "Money"):
        normalized = text.replace(",", "")
        if _INT_RE.match(normalized) or _FLOAT_RE.match(normalized):
            return normalized
        # Percent numbers con símbolo → texto (no adivinar formato).
    if friendly_type == "Boolean":
        lowered = text.strip().lower()
        if lowered in ("true", "yes", "si", "sí", "1"):
            return "TRUE"
        if lowered in ("false", "no", "0"):
            return "FALSE"
    return _quote(text)

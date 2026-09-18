# =============================================================================
# Tabular ingestion — mapa del Excel (schema map para UI/LLM/router)
# =============================================================================
# Construye una vista compacta de la representación estructurada:
# workbook → sheet → table → columnas (tipo, semántica, aliases).
# NO incluye filas: es el "mapa" que ve la UI y el contexto mínimo suficiente
# para que un agente sepa qué tablas/columnas existen antes de consultar SQL.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from src.core.ports.tabular import TabularRepository
from src.knowledge.tabular.lookup import (
    column_match_terms,
    normalize_question,
)

__all__ = [
    "TabularMap",
    "TabularMapColumn",
    "TabularMapTable",
    "TabularMapWorkbook",
    "build_tabular_map",
    "find_candidate_tables",
    "render_tabular_map_text",
]


@dataclass(frozen=True, kw_only=True)
class TabularMapColumn:
    id: str = ""
    normalized_name: str
    original_name: str = ""
    excel_letter: str = ""
    physical_column: int = 0
    inferred_type: str = "unknown"
    semantic_type: str = "unknown"
    aliases: tuple[str, ...] = ()
    description: str = ""

    @property
    def display_name(self) -> str:
        return self.original_name or self.normalized_name


@dataclass(frozen=True, kw_only=True)
class TabularMapTable:
    id: str
    name: str
    workbook_id: str = ""
    workbook: str = ""
    sheet: str = ""
    row_count: int = 0
    column_count: int = 0
    header_rows: tuple[int, ...] = ()
    detection_method: str = "heuristic"
    columns: tuple[TabularMapColumn, ...] = ()
    metadata: dict = field(default_factory=dict)

    def column_by_name(self, name: str) -> TabularMapColumn | None:
        wanted = (name or "").strip().lower()
        for column in self.columns:
            if column.normalized_name == wanted or column.original_name.lower() == wanted:
                return column
        return None


@dataclass(frozen=True, kw_only=True)
class TabularMapWorkbook:
    id: str
    filename: str
    format: str = "xlsx"
    sheet_count: int = 0
    table_count: int = 0
    row_count: int = 0
    quality_score: float | None = None
    representations: dict = field(default_factory=dict)
    source_id: str | None = None
    updated_at: object | None = None


@dataclass(frozen=True, kw_only=True)
class TabularMap:
    organization_id: UUID
    workbooks: tuple[TabularMapWorkbook, ...] = ()
    tables: tuple[TabularMapTable, ...] = ()

    @property
    def table_count(self) -> int:
        return len(self.tables)

    def table_by_id(self, table_id: str) -> TabularMapTable | None:
        for table in self.tables:
            if table.id == table_id:
                return table
        return None


async def build_tabular_map(
    repository: TabularRepository,
    organization_id: UUID,
    *,
    source_ids: list[UUID] | None = None,
    knowledge_base_id: UUID | None = None,
) -> TabularMap:
    """Mapa compacto del scope (org + opcional KB/fuentes)."""
    workbooks: list[dict] = []
    if source_ids:
        for source_id in source_ids[:20]:
            workbooks.extend(
                await repository.list_workbooks(
                    organization_id, source_id, knowledge_base_id=knowledge_base_id
                )
            )
        seen: set[str] = set()
        workbooks = [
            workbook
            for workbook in workbooks
            if not (workbook["id"] in seen or seen.add(workbook["id"]))
        ]
    else:
        workbooks = await repository.list_workbooks(
            organization_id, knowledge_base_id=knowledge_base_id
        )

    if not workbooks:
        return TabularMap(organization_id=organization_id)

    workbook_ids = {workbook["id"] for workbook in workbooks}
    filename_by_id = {
        workbook["id"]: workbook["filename"] for workbook in workbooks
    }

    tables_raw = await repository.list_tables(
        organization_id, knowledge_base_id=knowledge_base_id
    )
    tables_raw = [
        table for table in tables_raw if table["workbook_id"] in workbook_ids
    ]
    columns_raw = await repository.list_columns(
        organization_id, knowledge_base_id=knowledge_base_id
    )
    columns_by_table: dict[str, list[dict]] = {}
    for column in columns_raw:
        columns_by_table.setdefault(column["table_id"], []).append(column)

    tables: list[TabularMapTable] = []
    for table in tables_raw:
        columns = tuple(
            TabularMapColumn(
                id=column["id"],
                normalized_name=column["normalized_name"],
                original_name=column["original_name"],
                excel_letter=column["excel_letter"],
                physical_column=int(column["physical_column"]),
                inferred_type=column["inferred_type"],
                semantic_type=column["semantic_type"],
                aliases=tuple(column["aliases"] or ()),
                description=column["description"],
            )
            for column in columns_by_table.get(table["id"], [])
        )
        tables.append(
            TabularMapTable(
                id=table["id"],
                name=table["name"],
                workbook_id=table["workbook_id"],
                workbook=filename_by_id.get(table["workbook_id"], ""),
                sheet=table.get("sheet") or "",
                row_count=int(table["row_count"]),
                column_count=int(table["column_count"]),
                header_rows=tuple(table["header_rows"] or ()),
                detection_method=table["detection_method"],
                columns=columns,
                metadata={"title": table.get("title") or ""},
            )
        )

    return TabularMap(
        organization_id=organization_id,
        workbooks=tuple(
            TabularMapWorkbook(
                id=workbook["id"],
                filename=workbook["filename"],
                format=workbook["format"],
                sheet_count=int(workbook["sheet_count"]),
                table_count=int(workbook["table_count"]),
                row_count=int(workbook["row_count"]),
                quality_score=workbook.get("quality_score"),
                representations=workbook.get("representations") or {},
                source_id=workbook.get("source_id"),
                updated_at=workbook.get("updated_at"),
            )
            for workbook in workbooks
        ),
        tables=tuple(tables),
    )


def render_tabular_map_text(
    tabular_map: TabularMap,
    *,
    max_tables: int = 30,
    max_columns: int = 40,
    max_aliases: int = 4,
) -> str:
    """Texto compacto del mapa (prompt-safe: sin filas, sin valores masivos)."""
    lines: list[str] = [
        f"EXCEL MAP: {len(tabular_map.workbooks)} workbook(s), "
        f"{tabular_map.table_count} table(s)"
    ]
    for workbook in tabular_map.workbooks:
        representations = ", ".join(
            name
            for name, enabled in (workbook.representations or {}).items()
            if enabled
        )
        lines.append(
            f"Workbook: {workbook.filename} ({workbook.format}, "
            f"{workbook.sheet_count} sheet(s), {workbook.table_count} table(s), "
            f"{workbook.row_count} row(s)"
            + (
                f", quality {workbook.quality_score:.2f}"
                if workbook.quality_score is not None
                else ""
            )
            + (f", representations: {representations}" if representations else "")
            + ")"
        )
    for table in tabular_map.tables[:max_tables]:
        lines.append(
            f"  Sheet: {table.sheet} | Table: {table.name} "
            f"({table.row_count} row(s), {table.column_count} column(s), "
            f"header row(s) {list(table.header_rows)})"
        )
        for column in table.columns[:max_columns]:
            aliases = (
                " aliases: " + ", ".join(column.aliases[:max_aliases])
                if column.aliases
                else ""
            )
            lines.append(
                f"    {column.excel_letter} {column.display_name} "
                f"[{column.semantic_type}, {column.inferred_type}]{aliases}"
            )
    if tabular_map.table_count > max_tables:
        lines.append(f"  ... {tabular_map.table_count - max_tables} more table(s) omitted")
    return "\n".join(lines)


def find_candidate_tables(
    tabular_map: TabularMap,
    question: str,
    *,
    max_candidates: int = 3,
) -> list[tuple[TabularMapTable, float]]:
    """Ranking determinista tabla/columna para la pregunta.

    Señales: nombre de tabla, hoja, columnas (nombre/aliases/semántica).
    Si no hay señales y hay pocas tablas, se devuelven todas (pregunta
    genérica sobre un KB pequeño).
    """
    normalized = normalize_question(question)
    if not normalized:
        return []
    scored: list[tuple[float, TabularMapTable]] = []
    for table in tabular_map.tables:
        score = 0.0
        table_name = normalize_question(table.name)
        if table_name and table_name in normalized:
            score += 3.0
        sheet_name = normalize_question(table.sheet)
        if sheet_name and sheet_name in normalized:
            score += 1.5
        column_hits = 0
        for column in table.columns:
            for term in column_match_terms(
                {
                    "normalized_name": column.normalized_name,
                    "aliases": list(column.aliases),
                    "semantic_type": column.semantic_type,
                }
            ):
                term_normalized = normalize_question(term)
                if term_normalized and term_normalized in normalized:
                    column_hits += 1
                    break
        score += min(2.0, column_hits * 0.75)
        if score > 0:
            scored.append((score, table))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored:
        return [(table, score) for score, table in scored[:max_candidates]]
    if len(tabular_map.tables) <= max_candidates:
        return [(table, 0.5) for table in tabular_map.tables]
    return []

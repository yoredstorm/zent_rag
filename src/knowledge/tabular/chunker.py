# =============================================================================
# Tabular ingestion — chunking table-aware multinivel (brief §7 y §15)
# =============================================================================
# Niveles:
#   0 workbook summary      (parent)
#   1 sheet summary         (parent)
#   2 table schema          (parent)
#   3 row group window      (candidate + parent de filas)
#   4 individual row        (candidate)
#   5 cell/field            (opcional, default off)
#
# Nunca se separa una fila de sus encabezados: cada chunk de filas incluye el
# schema (nombre de columnas) y referencia el schema del nivel 2.
# Los parent_id de metadata apuntan al POINT ID determinista del padre para
# que la expansión de padres funcione igual que en el pipeline V2.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.knowledge_v2 import (
    ChunkType,
    DocumentChunk,
    KnowledgeObjectStatus,
    StructuredContentType,
    StructuredDocument,
)
from src.core.domain.tabular import (
    TabularColumn,
    TabularSemanticType,
    TabularSheet,
    TabularTable,
)
from src.knowledge.structure.base import content_hash, token_count
from src.knowledge.tabular.ids import (
    point_id_for,
    row_point_key,
    table_point_key,
)

_CHILD_CHAR_BUDGET = 4_000
_ROW_LINE_LIMIT = 600


@dataclass(frozen=True, kw_only=True)
class TabularChunkingConfig:
    """Política configurable de explosión de embeddings (brief §7)."""

    include_workbook_summary: bool = True
    include_sheet_summaries: bool = True
    include_schemas: bool = True
    include_row_groups: bool = True
    include_rows: bool = True
    include_cells: bool = False
    row_group_size: int = 40
    row_group_overlap: int = 2
    max_embedding_rows_per_table: int = 5_000
    # Cobertura semántica de filas vía row-groups: los grupos son baratos
    # (compactos) y cubren TODAS las filas hasta este cap de seguridad; las
    # filas individuales siguen capadas por `max_embedding_rows_per_table`.
    max_group_rows: int = 20_000
    max_cell_chunks_per_table: int = 200
    max_row_chars: int = 2_000
    max_group_chars: int = 6_000
    # Columnas de texto libre/descripción se recortan en los row-groups (el
    # texto completo sigue en la representación estructurada y en las filas
    # individuales capadas). Reduce tokens sin perder cobertura de filas.
    max_free_text_chars_in_groups: int = 160
    # Tablas anchas (> wide_table_columns): los row-groups muestran solo las
    # columnas clave (nombre/código/id/descripción/categoría) para bajar tokens;
    # el header conserva TODAS las columnas y los valores exactos viven en la
    # capa estructurada (SQL-first) y en las filas individuales capadas.
    key_columns_for_wide_tables: bool = True
    wide_table_columns: int = 12
    max_group_key_columns: int = 8


def chunk_tabular_workbook(
    document: StructuredDocument,
    *,
    config: TabularChunkingConfig | None = None,
    changed_table_ids: frozenset[UUID] | None = None,
) -> list[DocumentChunk]:
    """StructuredDocument tabular → DocumentChunks semánticos jerárquicos."""
    workbook = document.tabular
    if workbook is None:
        return []
    config = config or TabularChunkingConfig(
        row_group_size=int(workbook.metadata.get("row_group_size") or 20),
        row_group_overlap=int(workbook.metadata.get("row_group_overlap") or 2),
        max_embedding_rows_per_table=int(
            workbook.metadata.get("max_embedding_rows") or 5_000
        ),
    )

    chunks: list[DocumentChunk] = []
    index = 0

    def add(
        *,
        content: str,
        metadata: dict,
        level: int,
        chunk_type: ChunkType,
        parent_key: str | None,
        point_key: str,
        content_type: StructuredContentType = StructuredContentType.TEXT,
    ) -> DocumentChunk:
        nonlocal index
        chunk = DocumentChunk(
            id=uuid4(),
            document_id=document.id,
            organization_id=document.organization_id,
            workspace_id=document.workspace_id,
            source_id=document.source_id,
            corpus_id=document.corpus_id,
            chunk_index=index,
            chunk_type=chunk_type,
            parent_id=None,
            page_start=None,
            page_end=None,
            content=content,
            content_type=content_type,
            language=document.language,
            token_count=token_count(content),
            content_hash=content_hash(content),
            provenance=CatalogProvenance.OBSERVED,
            status=KnowledgeObjectStatus.OBSERVED,
            metadata={
                **metadata,
                "level": level,
                "point_key": point_key,
                "parent_id": (
                    str(point_id_for(parent_key)) if parent_key else None
                ),
                "v2_tabular": "true",
            },
        )
        index += 1
        chunks.append(chunk)
        return chunk

    def selected(table: TabularTable) -> bool:
        return changed_table_ids is None or table.id in changed_table_ids

    workbook_point_key = table_point_key(
        document.source_id, document.external_id, workbook.id, "workbook"
    )
    if config.include_workbook_summary:
        add(
            content=_render_workbook_summary(workbook),
            metadata=_workbook_metadata(document, workbook),
            level=0,
            chunk_type=ChunkType.DOCUMENT_STRUCTURE,
            parent_key=None,
            point_key=workbook_point_key,
        )

    for sheet in workbook.sheets:
        sheet_point_key = table_point_key(
            document.source_id, document.external_id, sheet.id, "sheet"
        )
        if config.include_sheet_summaries:
            add(
                content=_render_sheet_summary(document, workbook, sheet),
                metadata=_sheet_metadata(document, workbook, sheet),
                level=1,
                chunk_type=ChunkType.DOCUMENT_STRUCTURE,
                parent_key=workbook_point_key,
                point_key=sheet_point_key,
            )
        for table in sheet.tables:
            schema_point_key = table_point_key(
                document.source_id, document.external_id, table.id, "schema"
            )
            if config.include_schemas:
                add(
                    content=_render_table_schema(sheet, table),
                    metadata=_table_metadata(
                        document, workbook, sheet, table, parent_key=sheet_point_key
                    ),
                    level=2,
                    chunk_type=ChunkType.DOCUMENT_STRUCTURE,
                    parent_key=sheet_point_key,
                    point_key=schema_point_key,
                    content_type=StructuredContentType.TABLE,
                )
            if not selected(table):
                continue
            if config.include_row_groups:
                _emit_row_groups(
                    add=add,
                    document=document,
                    workbook=workbook,
                    sheet=sheet,
                    table=table,
                    config=config,
                    parent_key=schema_point_key,
                )
            if config.include_rows:
                _emit_rows(
                    add=add,
                    document=document,
                    workbook=workbook,
                    sheet=sheet,
                    table=table,
                    config=config,
                    parent_key=schema_point_key,
                )
            if config.include_cells:
                _emit_cells(
                    add=add,
                    document=document,
                    workbook=workbook,
                    sheet=sheet,
                    table=table,
                    config=config,
                    parent_key=schema_point_key,
                )
    return chunks


# ---------------------------------------------------------------------------
# Nivel 3: row groups
# ---------------------------------------------------------------------------


def _emit_row_groups(
    *,
    add,
    document: StructuredDocument,
    workbook,
    sheet: TabularSheet,
    table: TabularTable,
    config: TabularChunkingConfig,
    parent_key: str,
) -> None:
    rows = table.rows[: max(0, config.max_group_rows)]
    if not rows:
        return
    size = max(1, config.row_group_size)
    overlap = max(0, min(config.row_group_overlap, size - 1))
    step = max(1, size - overlap)
    for start in range(0, len(rows), step):
        window = rows[start : start + size]
        if not window:
            break
        text = _render_row_group(
            table,
            window,
            sheet.name,
            config.max_free_text_chars_in_groups,
            config.key_columns_for_wide_tables,
            config.wide_table_columns,
            config.max_group_key_columns,
        )
        for part_index, part in enumerate(_split_by_chars(text, config.max_group_chars)):
            point_key = table_point_key(
                document.source_id,
                document.external_id,
                table.id,
                "rowgroup",
                f"{window[0].physical_row}-{window[-1].physical_row}"
                + (f"-p{part_index}" if part_index else ""),
            )
            add(
                content=part,
                metadata={
                    **_table_metadata(
                        document, workbook, sheet, table, parent_key=parent_key
                    ),
                    "knowledge_type": "table_row_group",
                    "row_start": window[0].physical_row,
                    "row_end": window[-1].physical_row,
                    "row_group_size": len(window),
                    "row_group_part": part_index,
                },
                level=3,
                chunk_type=ChunkType.TABLE_AWARE,
                parent_key=parent_key,
                point_key=point_key,
            )


def _render_row_group(
    table: TabularTable,
    rows,
    sheet_name: str = "",
    max_free_text_chars: int = 160,
    key_columns_for_wide_tables: bool = True,
    wide_table_columns: int = 12,
    max_group_key_columns: int = 8,
) -> str:
    """Row-group COMPACTO v3: header corto + una línea por fila (posicional).

    Formato: `TABLE/SHEET/ROWS`, `KEY: <columnas clave>` y filas con los valores
    de esas columnas en orden. En tablas anchas se omiten las columnas no clave
    (quedan completas en la representación estructurada) y las de texto libre se
    recortan. El header corto deja ver ~15 filas dentro de los presupuestos de
    contexto de agentes y herramientas (antes el COLUMNS de 24 columnas se comía
    el presupuesto y el match quedaba fuera).
    """
    key_columns = _group_key_columns(
        table, key_columns_for_wide_tables, wide_table_columns, max_group_key_columns
    )
    key_names = [
        _compact_name(column.original_name or column.normalized_name)
        for column in key_columns
    ]
    sheet_part = f" | SHEET: {_compact_name(sheet_name)}" if sheet_name else ""
    lines = [
        f"TABLE: {_compact_name(table.name)}{sheet_part} | "
        f"ROWS: {rows[0].physical_row}-{rows[-1].physical_row}",
        "KEY: " + " | ".join(key_names),
    ]
    if len(key_columns) < len(table.columns):
        lines.append(
            "NOTE: key columns shown; full row available in the structured layer"
        )
    for row in rows:
        cells = [
            _compact_cell(row.value_for(column), column, max_free_text_chars)
            for column in key_columns
        ]
        lines.append(f"{row.physical_row}: " + " | ".join(cells))
    return "\n".join(lines)


_KEY_SEMANTIC_PRIORITY = (
    TabularSemanticType.NAME,
    TabularSemanticType.CODE,
    TabularSemanticType.DESCRIPTION,
    TabularSemanticType.FREE_TEXT,
    TabularSemanticType.CATEGORY,
    TabularSemanticType.REFERENCE,
    # Los identificadores numéricos van al final: el prefijo de fila física ya
    # identifica la fila; su valor exacto vive en la capa estructurada.
    TabularSemanticType.IDENTIFIER,
)

# Columnas de valor corto (posiciones, tamaños, flags, fechas, códigos): son
# baratas en tokens y son la información que más se consulta en data
# dictionaries ("¿dónde empieza X?", "¿cuánto mide?"). Se incluyen en los
# row-groups de tablas anchas después de las columnas semánticas.
_SHORT_VALUE_CHARS = 12
_SHORT_VALUE_SAMPLE_ROWS = 200
_POSITION_HINTS = (
    "loc", "pos", "size", "len", "start", "end", "offset", "range", "mide",
)


def _group_key_columns(
    table: TabularTable,
    enabled: bool,
    wide_table_columns: int,
    max_key_columns: int,
) -> list:
    """Columnas que se rinden en los row-groups (todas si la tabla es angosta).

    En tablas anchas se reserva espacio para columnas de posición/longitud: son
    las que más se consultan en data dictionaries y ocupan pocos tokens. El
    resto lo llenan las columnas semánticas (nombre/descripción) y, si sobra,
    otras columnas cortas (códigos, flags).
    """
    if not enabled or len(table.columns) <= wide_table_columns:
        return list(table.columns)
    cap = max(1, max_key_columns)
    reserve = min(3, max(1, cap // 3))
    semantic_slots = max(1, cap - reserve)
    selected: list = []
    for semantic in _KEY_SEMANTIC_PRIORITY:
        for column in table.columns:
            if column.semantic_type is semantic and column not in selected:
                selected.append(column)
            if len(selected) >= semantic_slots:
                break
        if len(selected) >= semantic_slots:
            break
    for column in _short_value_columns(table):
        if column not in selected:
            selected.append(column)
        if len(selected) >= cap:
            break
    if not selected:
        selected = list(table.columns[:3])
    return selected[:cap]


def _short_value_columns(table: TabularTable) -> list:
    """Columnas de valor corto; posición/longitud primero, resto por longitud.

    Excluye texto libre (ya está en las semánticas) e identificadores (el número
    de fila física ya identifica la fila).
    """
    sample = table.rows[: _SHORT_VALUE_SAMPLE_ROWS]
    if not sample:
        return []
    position_columns: list[tuple[float, int, object]] = []
    other_columns: list[tuple[float, int, object]] = []
    for index, column in enumerate(table.columns):
        if column.semantic_type in _FREE_TEXT_SEMANTICS:
            continue
        if column.semantic_type is TabularSemanticType.IDENTIFIER:
            continue
        lengths = [
            len(value)
            for row in sample
            if (value := row.value_for(column))
        ]
        if not lengths:
            continue
        average = sum(lengths) / len(lengths)
        if average > _SHORT_VALUE_CHARS:
            continue
        name = (column.normalized_name or "").lower()
        hinted = any(hint in name for hint in _POSITION_HINTS)
        bucket = position_columns if hinted else other_columns
        bucket.append((average, index, column))
    position_columns.sort(key=lambda item: (item[0], item[1]))
    other_columns.sort(key=lambda item: (item[0], item[1]))
    return [column for _a, _i, column in position_columns] + [
        column for _a, _i, column in other_columns
    ]


_FREE_TEXT_SEMANTICS = (
    TabularSemanticType.DESCRIPTION,
    TabularSemanticType.FREE_TEXT,
)


def _compact_name(value: str) -> str:
    """Sanitiza nombres (tabla/hoja/columna) para líneas del row-group."""
    if not value:
        return ""
    return value.replace("|", "/").replace("\r", " ").replace("\n", " ").strip()


def _compact_cell(
    value: str, column: TabularColumn, max_free_text_chars: int = 160
) -> str:
    """Sanitiza una celda para el formato posicional (sin pipes ni saltos)."""
    if not value:
        return ""
    text = value.replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    if column.semantic_type in _FREE_TEXT_SEMANTICS:
        limit = max(32, int(max_free_text_chars))
    else:
        limit = _ROW_LINE_LIMIT
    return _clip(text, limit)


# ---------------------------------------------------------------------------
# Nivel 4: filas
# ---------------------------------------------------------------------------


def _emit_rows(
    *,
    add,
    document: StructuredDocument,
    workbook,
    sheet: TabularSheet,
    table: TabularTable,
    config: TabularChunkingConfig,
    parent_key: str,
) -> None:
    limit = config.max_embedding_rows_per_table
    for row in table.rows[: max(0, limit)]:
        content = _render_row(table, sheet, workbook, row)
        for part_index, part in enumerate(
            _split_by_column_parts(table, row, sheet, workbook, config.max_row_chars)
        ):
            point_key = row_point_key(
                document.source_id, document.external_id, table.id, row.physical_row
            )
            if part_index:
                point_key = f"{point_key}:p{part_index}"
            add(
                content=part,
                metadata={
                    **_table_metadata(
                        document, workbook, sheet, table, parent_key=parent_key
                    ),
                    "knowledge_type": "table_row",
                    "row_start": row.physical_row,
                    "row_end": row.physical_row,
                    "physical_row": row.physical_row,
                    "row_index": row.logical_index,
                    "row_part": part_index,
                    "row_hash": row.content_hash,
                    "values": row.mapping(table.columns),
                },
                level=4,
                chunk_type=ChunkType.TABLE_AWARE,
                parent_key=parent_key,
                point_key=point_key,
            )


def _render_row(table: TabularTable, sheet: TabularSheet, workbook, row) -> str:
    lines = [
        f"Workbook: {workbook.filename}",
        f"Sheet: {sheet.name}",
        f"Table: {table.name}",
        f"Row: {row.physical_row}",
    ]
    for column in table.columns:
        value = row.value_for(column)
        if value == "":
            continue
        lines.append(f"{column.original_name or column.normalized_name}: {value}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Nivel 5: celda/campo (opcional)
# ---------------------------------------------------------------------------

_CELL_SEMANTIC_TYPES = {
    TabularSemanticType.POSITION,
    TabularSemanticType.LENGTH,
    TabularSemanticType.AMOUNT,
    TabularSemanticType.QUANTITY,
    TabularSemanticType.PERCENTAGE,
    TabularSemanticType.DATE,
}


def _emit_cells(
    *,
    add,
    document: StructuredDocument,
    workbook,
    sheet: TabularSheet,
    table: TabularTable,
    config: TabularChunkingConfig,
    parent_key: str,
) -> None:
    label_column = next(
        (
            candidate
            for candidate in table.columns
            if candidate.semantic_type
            in (
                TabularSemanticType.NAME,
                TabularSemanticType.IDENTIFIER,
                TabularSemanticType.CODE,
            )
        ),
        None,
    )
    emitted = 0
    for row in table.rows:
        if emitted >= config.max_cell_chunks_per_table:
            break
        for column in table.columns:
            if column.semantic_type not in _CELL_SEMANTIC_TYPES:
                continue
            value = row.value_for(column).strip()
            if not value or len(value) > 120:
                continue
            label = column.original_name or column.normalized_name
            row_label = row.value_for(label_column) if label_column is not None else ""
            prefix = f"{table.name} > {row_label or ('Row ' + str(row.physical_row))}"
            add(
                content=f"{prefix} > {label} = {value}",
                metadata={
                    **_table_metadata(
                        document, workbook, sheet, table, parent_key=parent_key
                    ),
                    "knowledge_type": "table_cell",
                    "physical_row": row.physical_row,
                    "physical_column": column.physical_column,
                    "cell_address": f"{column.excel_letter}{row.physical_row}",
                    "column": column.normalized_name,
                },
                level=5,
                chunk_type=ChunkType.TABLE_AWARE,
                parent_key=parent_key,
                point_key=table_point_key(
                    document.source_id,
                    document.external_id,
                    table.id,
                    "cell",
                    f"{row.physical_row}:{column.physical_column}",
                ),
            )
            emitted += 1
            if emitted >= config.max_cell_chunks_per_table:
                break


# ---------------------------------------------------------------------------
# Resúmenes / schema
# ---------------------------------------------------------------------------


def _render_workbook_summary(workbook) -> str:
    lines = [
        f"Workbook: {workbook.filename}",
        f"Format: {workbook.format.value}",
        f"Sheets: {workbook.sheet_count}",
        f"Tables: {workbook.table_count}",
        f"Rows: {workbook.row_count}",
    ]
    if workbook.profile is not None:
        lines.append(f"Non-empty cells: {workbook.profile.non_empty_cells}")
        if workbook.profile.formulas:
            lines.append(f"Formulas: {workbook.profile.formulas}")
    if workbook.quality is not None:
        lines.append(
            f"Quality score: {workbook.quality.quality_score:.2f} "
            f"({workbook.quality.warning_count} warnings)"
        )
    lines.append("SHEETS:")
    for sheet in workbook.sheets:
        lines.append(
            f"- {sheet.name}: {sheet.table_count} table(s), {sheet.row_count} rows"
            + (" (hidden)" if sheet.hidden else "")
        )
    return "\n".join(lines)


def _render_sheet_summary(document, workbook, sheet: TabularSheet) -> str:
    lines = [
        f"Sheet: {sheet.name}",
        f"Workbook: {workbook.filename}",
        f"Tables: {sheet.table_count}",
    ]
    if sheet.tables:
        all_columns: list[str] = []
        for table in sheet.tables:
            for column in table.columns:
                name = column.original_name or column.normalized_name
                if name not in all_columns:
                    all_columns.append(name)
        lines.append("Columns: " + ", ".join(all_columns[:40]))
        for table in sheet.tables:
            lines.append(
                f"TABLE: {table.name} — rows {table.range.min_row}-{table.range.max_row}, "
                f"{table.row_count} data rows, columns: "
                + ", ".join(
                    column.original_name or column.normalized_name
                    for column in table.columns[:20]
                )
            )
    for block in sheet.context_blocks[:5]:
        lines.append(f"Context ({block.kind.value}): {_clip(block.text, 200)}")
    return "\n".join(lines)


def _render_table_schema(sheet: TabularSheet, table: TabularTable) -> str:
    lines = [
        f"TABLE: {table.name}",
        f"Sheet: {sheet.name}",
    ]
    if table.title:
        lines.append(f"Title: {table.title}")
    for block in table.context_blocks:
        if block.kind.value in ("title", "subtitle"):
            lines.append(f"Context ({block.kind.value}): {_clip(block.text, 200)}")
    lines.append("COLUMNS:")
    for column in table.columns:
        type_hint = column.inferred_type.value
        semantic_hint = column.semantic_type.value
        lines.append(
            f"- {column.original_name or column.normalized_name} "
            f"[{column.excel_letter}{table.range.min_row}] ({semantic_hint}, {type_hint})"
            + (f" — {column.description}" if column.description else "")
        )
    lines.append(
        f"Header rows: {', '.join(str(row) for row in table.header_rows) or 'none'}"
    )
    if table.rows:
        lines.append(
            f"Rows: {table.rows[0].physical_row}-{table.rows[-1].physical_row} "
            f"({table.row_count} data rows)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def _base_metadata(document: StructuredDocument, workbook) -> dict:
    return {
        "format": workbook.format.value,
        "source_id": str(document.source_id) if document.source_id else None,
        "external_id": document.external_id,
        "workbook": workbook.filename,
        "workbook_id": str(workbook.id),
        "workspace_id": str(document.workspace_id) if document.workspace_id else None,
        "document_id": str(document.id),
        "v2_doc": "true",
        "chunking_strategy": "tabular",
    }


def _workbook_metadata(document: StructuredDocument, workbook) -> dict:
    return {
        **_base_metadata(document, workbook),
        "knowledge_type": "table_workbook",
    }


def _sheet_metadata(document: StructuredDocument, workbook, sheet: TabularSheet) -> dict:
    return {
        **_base_metadata(document, workbook),
        "knowledge_type": "table_sheet",
        "sheet": sheet.name,
        "sheet_id": str(sheet.id),
        "sheet_index": sheet.index,
        "tables": [table.name for table in sheet.tables],
    }


def _table_metadata(
    document: StructuredDocument,
    workbook,
    sheet: TabularSheet,
    table: TabularTable,
    *,
    parent_key: str | None = None,
) -> dict:
    metadata = {
        **_base_metadata(document, workbook),
        "knowledge_type": "table_schema",
        "sheet": sheet.name,
        "sheet_id": str(sheet.id),
        "sheet_index": sheet.index,
        "table_id": str(table.id),
        "table_name": table.name,
        "columns": [column.normalized_name for column in table.columns],
        "column_names": [
            column.original_name or column.normalized_name for column in table.columns
        ],
        "header_row": table.header_rows[0] if table.header_rows else None,
        "header_rows": list(table.header_rows),
        "detection_method": table.detection_method.value,
        "detection_confidence": table.detection_confidence,
        "header_confidence": table.header_confidence,
        "schema_hash": table.schema_hash,
        "table_content_hash": table.content_hash,
        "table_range": {
            "min_row": table.range.min_row,
            "max_row": table.range.max_row,
            "min_col": table.range.min_col,
            "max_col": table.range.max_col,
        },
    }
    if parent_key:
        metadata["schema_id"] = str(point_id_for(parent_key))
    return metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def _split_by_chars(text: str, max_chars: int) -> list[str]:
    """Divide un row-group por presupuesto, repitiendo SOLO cabecera+COLUMNS."""
    if len(text) <= max_chars:
        return [text]
    lines = text.splitlines()
    prefix = lines[:2] if len(lines) >= 2 else lines[:1]
    parts: list[str] = []
    current = list(prefix)
    for line in lines[len(prefix) :]:
        if len("\n".join(current)) + len(line) + 1 > max_chars and len(current) > len(prefix):
            parts.append("\n".join(current))
            current = list(prefix)
        current.append(line)
    if current:
        parts.append("\n".join(current))
    return parts or [text[:max_chars]]


def _split_by_column_parts(
    table: TabularTable,
    row,
    sheet: TabularSheet,
    workbook,
    max_chars: int,
) -> list[str]:
    content = _render_row(table, sheet, workbook, row)
    if len(content) <= max_chars:
        return [content]
    parts: list[str] = []
    current: list[str] = []
    header = [
        f"Workbook: {workbook.filename}",
        f"Sheet: {sheet.name}",
        f"Table: {table.name}",
        f"Row: {row.physical_row}",
    ]
    current_size = len("\n".join(header)) + 1
    for column in table.columns:
        value = row.value_for(column)
        if value == "":
            continue
        line = f"{column.original_name or column.normalized_name}: {value}"
        if current and current_size + len(line) + 1 > max_chars:
            parts.append("\n".join(header + current))
            current = []
            current_size = len("\n".join(header)) + 1
        current.append(line)
        current_size += len(line) + 1
    if current:
        parts.append("\n".join(header + current))
    return parts or [content[:max_chars]]

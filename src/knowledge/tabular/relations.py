# =============================================================================
# Tabular ingestion — relaciones candidatas entre tablas (señales, no joins)
# =============================================================================
# Detecta columnas candidatas a join/lookup/hierarchy por nombre normalizado,
# tipo y solapamiento de valores. NUNCA se ejecuta un join en ingesta: solo se
# guardan señales con confidence y evidencia para el retrieval/router futuro.
# =============================================================================
from __future__ import annotations

from src.core.domain.catalog import CatalogProvenance
from src.core.domain.tabular import (
    TabularColumn,
    TabularRelation,
    TabularRelationKind,
    TabularSemanticType,
    TabularTable,
    TabularValueType,
    TabularWorkbook,
)
from src.knowledge.tabular.ids import relation_id

_MAX_TABLES = 40
_MAX_COLUMNS_PER_TABLE = 200
_MAX_RELATIONS = 200
_VALUE_SAMPLE = 300
_MIN_OVERLAP = 0.5


def discover_relations(workbook: TabularWorkbook) -> tuple[TabularRelation, ...]:
    tables = workbook.tables()[:_MAX_TABLES]
    if len(tables) < 2:
        return ()

    profiles: dict[tuple, _ColumnSignal] = {}
    for table in tables:
        for column in table.columns[:_MAX_COLUMNS_PER_TABLE]:
            profiles[(table.id, column.id)] = _column_signal(table, column)

    relations: list[TabularRelation] = []
    for index, left in enumerate(tables):
        for right in tables[index + 1 :]:
            relations.extend(_pair_relations(left, right, profiles))
            if len(relations) >= _MAX_RELATIONS:
                return tuple(relations[:_MAX_RELATIONS])
    return tuple(relations[:_MAX_RELATIONS])


class _ColumnSignal:
    __slots__ = ("column", "name", "values", "kind", "semantic")

    def __init__(self, column: TabularColumn, values: frozenset[str]):
        self.column = column
        self.name = column.normalized_name
        self.values = values
        self.kind = column.inferred_type
        self.semantic = column.semantic_type


def _column_signal(table: TabularTable, column: TabularColumn) -> _ColumnSignal:
    joinable = column.semantic_type in (
        TabularSemanticType.IDENTIFIER,
        TabularSemanticType.CODE,
        TabularSemanticType.REFERENCE,
        TabularSemanticType.CATEGORY,
    ) or column.inferred_type in (
        TabularValueType.IDENTIFIER,
        TabularValueType.CODE,
    )
    if not joinable or column.unique_ratio < 0.5:
        return _ColumnSignal(column, frozenset())
    values: set[str] = set()
    for row in table.rows:
        value = row.value_for(column).strip()
        if value:
            values.add(value)
        if len(values) >= _VALUE_SAMPLE:
            break
    return _ColumnSignal(column, frozenset(values))


def _pair_relations(
    left: TabularTable,
    right: TabularTable,
    profiles: dict[tuple, _ColumnSignal],
) -> list[TabularRelation]:
    results: list[TabularRelation] = []
    same_sheet = left.sheet_id == right.sheet_id
    for left_column in left.columns[:_MAX_COLUMNS_PER_TABLE]:
        left_signal = profiles.get((left.id, left_column.id))
        if left_signal is None:
            continue
        for right_column in right.columns[:_MAX_COLUMNS_PER_TABLE]:
            right_signal = profiles.get((right.id, right_column.id))
            if right_signal is None:
                continue
            same_name = (
                left_signal.name
                and left_signal.name == right_signal.name
                and len(left_signal.name) >= 3
            )
            same_type = left_signal.kind == right_signal.kind
            overlap = _value_overlap(left_signal.values, right_signal.values)
            if not same_name and overlap < _MIN_OVERLAP:
                continue
            if same_name:
                confidence = 0.6 + (0.2 if same_type else 0.0) + (0.15 if overlap >= _MIN_OVERLAP else 0.0)
                kind = (
                    TabularRelationKind.CANDIDATE_HIERARCHY
                    if same_sheet
                    else TabularRelationKind.CANDIDATE_JOIN
                )
            else:
                confidence = min(0.9, 0.35 + overlap * 0.5)
                kind = TabularRelationKind.CANDIDATE_LOOKUP
            evidence = {
                "same_name": bool(same_name),
                "same_type": bool(same_type),
                "value_overlap": round(overlap, 3),
                "left_table": left.name,
                "right_table": right.name,
                "left_column": left_column.original_name,
                "right_column": right_column.original_name,
            }
            results.append(
                TabularRelation(
                    id=relation_id(left.workbook_id, left_column.id, right_column.id, kind.value),
                    workbook_id=left.workbook_id,
                    from_table_id=left.id,
                    from_column_id=left_column.id,
                    to_table_id=right.id,
                    to_column_id=right_column.id,
                    kind=kind,
                    confidence=round(min(1.0, confidence), 3),
                    evidence=evidence,
                    provenance=CatalogProvenance.INFERRED,
                )
            )
    return results


def _value_overlap(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if not intersection:
        return 0.0
    return intersection / max(1, min(len(left), len(right)))

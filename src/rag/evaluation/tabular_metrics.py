# =============================================================================
# Evaluation — Tabular RAG metrics (golden dataset §34)
# =============================================================================
# Métricas deterministas para respuestas sobre tablas: recuperación de tabla,
# fila y columnas + accuracy de valor exacto y de cita (provenance). No mide
# similitud textual: mide si el sistema encontró el dato correcto.
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "TabularGoldenCase",
    "TabularGoldenResult",
    "load_tabular_golden",
    "table_recall_at_k",
    "row_recall_at_k",
    "column_recall_at_k",
    "exact_value_accuracy",
    "citation_accuracy",
    "evaluate_tabular_case",
]


@dataclass(frozen=True, kw_only=True)
class TabularGoldenCase:
    id: str
    question: str
    expected_answer: str
    expected_table: str
    expected_sheet: str | None = None
    expected_row: int | None = None
    expected_columns: tuple[str, ...] = ()
    expected_cell: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TabularGoldenResult:
    case: TabularGoldenCase
    answer: str | None = None
    table_hit: bool = False
    row_hit: bool = False
    columns_hit: float = 0.0
    exact_value: bool = False
    citation_ok: bool = False
    retrieved: dict = field(default_factory=dict)
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.case.id,
            "question": self.case.question,
            "expected_answer": self.case.expected_answer,
            "answer": self.answer,
            "table_hit": self.table_hit,
            "row_hit": self.row_hit,
            "columns_hit": self.columns_hit,
            "exact_value": self.exact_value,
            "citation_ok": self.citation_ok,
            "latency_ms": self.latency_ms,
        }


def load_tabular_golden(path: str | Path) -> list[TabularGoldenCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    return [
        TabularGoldenCase(
            id=str(case["id"]),
            question=str(case["question"]),
            expected_answer=str(case.get("expected_answer", "")),
            expected_table=str(case.get("expected_table", "")),
            expected_sheet=case.get("expected_sheet"),
            expected_row=case.get("expected_row"),
            expected_columns=tuple(str(c) for c in case.get("expected_columns", [])),
            expected_cell=case.get("expected_cell"),
            metadata=case.get("metadata") or {},
        )
        for case in cases
    ]


# ---------------------------------------------------------------------------
# Métricas de retrieval
# ---------------------------------------------------------------------------


def table_recall_at_k(retrieved_tables: list[str], expected_table: str, k: int = 5) -> float:
    top = [str(name).strip().lower() for name in retrieved_tables[:k]]
    return 1.0 if expected_table.strip().lower() in top else 0.0


def row_recall_at_k(retrieved_rows: list[int], expected_row: int | None, k: int = 5) -> float:
    if expected_row is None:
        return 0.0
    return 1.0 if int(expected_row) in [int(row) for row in retrieved_rows[:k]] else 0.0


def column_recall_at_k(
    retrieved_columns: list[str], expected_columns: tuple[str, ...] | list[str], k: int = 10
) -> float:
    if not expected_columns:
        return 1.0
    top = [str(name).strip().lower() for name in retrieved_columns[:k]]
    hits = sum(
        1 for column in expected_columns if str(column).strip().lower() in top
    )
    return hits / len(expected_columns)


def exact_value_accuracy(actual: str | None, expected: str) -> float:
    if actual is None:
        return 0.0
    return 1.0 if str(actual).strip() == str(expected).strip() else 0.0


def citation_accuracy(
    *,
    table: str | None,
    row: int | None,
    column: str | None,
    case: TabularGoldenCase,
) -> float:
    """Cita correcta: tabla + fila + (celda o columna) coinciden."""
    if table is None or case.expected_table.strip().lower() != str(table).strip().lower():
        return 0.0
    if case.expected_row is not None and row is not None and int(row) != int(case.expected_row):
        return 0.0
    if case.expected_columns:
        wanted = [c.strip().lower() for c in case.expected_columns]
        if column is None or str(column).strip().lower() not in wanted:
            return 0.0
    return 1.0


def evaluate_tabular_case(
    case: TabularGoldenCase,
    *,
    answer: str | None,
    retrieved_tables: list[str],
    retrieved_rows: list[int],
    retrieved_columns: list[str],
    citation: dict | None = None,
    k: int = 5,
    latency_ms: float = 0.0,
) -> TabularGoldenResult:
    citation = citation or {}
    return TabularGoldenResult(
        case=case,
        answer=answer,
        table_hit=bool(table_recall_at_k(retrieved_tables, case.expected_table, k)),
        row_hit=bool(row_recall_at_k(retrieved_rows, case.expected_row, k)),
        columns_hit=column_recall_at_k(retrieved_columns, case.expected_columns, k),
        exact_value=bool(exact_value_accuracy(answer, case.expected_answer)),
        citation_ok=bool(
            citation_accuracy(
                table=citation.get("table"),
                row=citation.get("row"),
                column=citation.get("column"),
                case=case,
            )
        ),
        retrieved={
            "tables": retrieved_tables,
            "rows": retrieved_rows,
            "columns": retrieved_columns,
        },
        latency_ms=latency_ms,
    )

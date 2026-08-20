# =============================================================================
# Vertical demo_farmacia — Heurísticas SQL específicas de ventas de farmacia
# =============================================================================
# Registradas dinámicamente vía RAG_SQL_HEURISTICS_MODULES. El core del
# SQL Expert no conoce "sales", "order_status" ni "ventas".
# =============================================================================
from __future__ import annotations

import re

import sqlglot

from src.agents.tools.sql_expert_postgres import register_sql_heuristic

_LAST_SALE_QUESTION = re.compile(
    r"(últim[oa]|ultim[oa]|ultimo|ultima|last|most recent|latest).{0,80}(vendid|venta|sold)|"
    r"(vendid|venta|sold).{0,80}(últim[oa]|ultim[oa]|ultimo|ultima|last|más reciente|mas reciente)",
    re.IGNORECASE | re.DOTALL,
)


def _sales_alias(select: sqlglot.exp.Select) -> str | None:
    for table in select.find_all(sqlglot.exp.Table):
        if table.name.lower() == "sales":
            return table.alias_or_name
    return None


def _has_order_status_predicate(select: sqlglot.exp.Select) -> bool:
    for col in select.find_all(sqlglot.exp.Column):
        if col.name.lower() == "order_status":
            return True
    return False


def _last_sale_completed_filter(question: str, parsed: sqlglot.exp.Select) -> sqlglot.exp.Select | None:
    """Para preguntas de 'última venta': fuerza order_status='completed'."""
    if not _LAST_SALE_QUESTION.search(question):
        return None
    sales_alias = _sales_alias(parsed)
    if not sales_alias or _has_order_status_predicate(parsed):
        return None
    return parsed.where(
        sqlglot.exp.EQ(
            this=sqlglot.exp.Column(
                this=sqlglot.exp.to_identifier("order_status"),
                table=sqlglot.exp.to_identifier(sales_alias),
            ),
            expression=sqlglot.exp.Literal.string("completed"),
        )
    )


def register() -> None:
    register_sql_heuristic("demo_farmacia.last_sale_completed", _last_sale_completed_filter)

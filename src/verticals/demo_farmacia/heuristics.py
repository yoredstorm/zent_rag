# =============================================================================
# Vertical demo_farmacia — Heurísticas SQL específicas de ventas de farmacia
# =============================================================================
# Registradas dinámicamente vía RAG_SQL_HEURISTICS_MODULES. El core del
# SQL Expert no conoce "sales", "order_status" ni "ventas".
# =============================================================================
from __future__ import annotations

import re
import unicodedata

import sqlglot

from src.agents.tools.sql_expert_postgres import register_sql_heuristic

_LAST_SALE_QUESTION = re.compile(
    r"(últim[oa]|ultim[oa]|ultimo|ultima|last|most recent|latest).{0,80}(vendid|venta|sold)|"
    r"(vendid|venta|sold).{0,80}(últim[oa]|ultim[oa]|ultimo|ultima|last|más reciente|mas reciente)",
    re.IGNORECASE | re.DOTALL,
)
_PRODUCT_NEED = re.compile(
    r"analg[eé]sic\w*|antiinflam\w*|antipir[eé]t\w*|antibiot\w*|"
    r"antigrip\w*|alerg\w*|vitamin\w*|\bdolor\b|\bfiebre\b",
    re.IGNORECASE,
)


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn")


def _sales_alias(select: sqlglot.exp.Select) -> str | None:
    for table in select.find_all(sqlglot.exp.Table):
        if table.name.lower() == "sales":
            return table.alias_or_name
    return None


def _product_alias(select: sqlglot.exp.Select) -> str | None:
    for table in select.find_all(sqlglot.exp.Table):
        if table.name.lower() in {"products", "vw_product_catalog"}:
            return table.alias_or_name
    return None


def _category_alias(select: sqlglot.exp.Select) -> str | None:
    for table in select.find_all(sqlglot.exp.Table):
        if table.name.lower() == "categories":
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


def _catalog_terms(question: str) -> set[str]:
    terms: set[str] = set()
    for match in _PRODUCT_NEED.finditer(question or ""):
        raw = match.group(0)
        folded = _fold(raw)
        terms.add(raw.lower())
        terms.add(folded)
        if folded.startswith("analg"):
            terms.update({"analgesico", "analgésico", "analgesicos", "analgésicos"})
    return {t.replace("'", "''") for t in terms if t}


def _expand_product_text_search(
    question: str, parsed: sqlglot.exp.Select
) -> sqlglot.exp.Select | None:
    """ILIKE en name no basta: Paracetamol no se llama 'analgésico'."""
    product = _product_alias(parsed)
    if product is None:
        return None
    terms = _catalog_terms(question)
    if not terms:
        return None
    where = parsed.args.get("where")
    snapshot = where.sql().lower() if where is not None else ""
    if "tags" in snapshot and "description" in snapshot:
        return None

    likes: list[str] = []
    category = _category_alias(parsed)
    for term in sorted(terms):
        pattern = f"%{term}%"
        likes.append(f"{product}.name ILIKE '{pattern}'")
        likes.append(f"{product}.description ILIKE '{pattern}'")
        likes.append(f"CAST({product}.tags AS text) ILIKE '{pattern}'")
        if category:
            likes.append(f"{category}.name ILIKE '{pattern}'")
    extra = sqlglot.parse_one(" OR ".join(likes))
    return parsed.where(extra)


def register() -> None:
    register_sql_heuristic("demo_farmacia.last_sale_completed", _last_sale_completed_filter)
    register_sql_heuristic("demo_farmacia.catalog_text_search", _expand_product_text_search)

from __future__ import annotations

import re
from uuid import UUID

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports import LLMProvider
from src.domain.services import ColumnMeta, DataSource
from src.domain.sql_expert import SqlExpert, SqlQueryResult, SqlValidationError
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import get_async_session
from src.infrastructure.schema_discovery import (
    SYSTEM_SCHEMAS,
    SYSTEM_TABLES,
)
from src.infrastructure.schema_discovery import (
    discover_columns as fetch_columns,
)
from src.infrastructure.schema_discovery import (
    discover_sources as fetch_sources,
)

logger = get_logger(__name__)

# Palabras prohibidas en SQL — prevención de inyección estructural
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE"
    r"|EXECUTE|GRANT|REVOKE|COPY|VACUUM|REINDEX"
    r"|SET\s+role|RESET\s+role|pg_read_file|pg_write_file"
    r"|lo_import|lo_export)\b",
    re.IGNORECASE,
)


_READ_ONLY_STATEMENTS = {"select", "describe"}


def _validate_sql_ast(sql: str) -> None:
    """Valida que el SQL sea solo SELECT/EXPLAIN/SHOW usando sqlglot AST.

    Bloquea ataques por CTE como:
        WITH x AS (DELETE FROM ventas RETURNING *) SELECT * FROM x
    que pasan un check ingenuo de primera palabra.
    """
    from sqlglot.errors import ParseError as SqlglotParseError

    try:
        statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except SqlglotParseError as exc:
        raise SqlValidationError(f"Invalid SQL syntax: {exc}", sql) from exc

    if not statements:
        raise SqlValidationError("Empty or unparseable SQL", sql)

    for stmt in statements:
        stmt_type = stmt.key.lower() if stmt.key else "unknown"
        if stmt_type not in _READ_ONLY_STATEMENTS:
            raise SqlValidationError(
                f"Only SELECT statements allowed, found: {stmt_type}", sql
            )

        _check_ctes(stmt, sql)

        _check_subqueries(stmt, sql)


def _check_ctes(statement, sql: str) -> None:
    """Recorre CTEs buscando statements no-SELECT anidados."""
    if not hasattr(statement, "ctes"):
        return
    for cte in statement.ctes:
        if not cte.this:
            continue
        cte_type = cte.this.key.lower() if cte.this.key else "unknown"
        if cte_type != "select":
            raise SqlValidationError(
                f"Non-SELECT statement inside CTE: {cte_type}", sql
            )
        _check_ctes(cte.this, sql)
        _check_subqueries(cte.this, sql)


def _check_subqueries(expression, sql: str) -> None:
    """Recorre subqueries anidadas buscando statements no-SELECT."""
    try:
        for node in expression.find_all(sqlglot.exp.Query):
            node_type = node.key.lower() if node.key else "unknown"
            if node_type != "select":
                raise SqlValidationError(
                    f"Non-SELECT subquery: {node_type}", sql
                )
    except Exception:
        pass


def _format_sql_result(result: SqlQueryResult, question: str) -> str:
    """Formatea resultados SQL para presentación al LLM."""
    if not result.rows:
        return "No results found."
    header = " | ".join(result.columns)
    rows_text = "\n".join(
        " | ".join(row) for row in result.rows[:50]
    )
    return f"Question: {question}\nColumns: {header}\nRows ({result.row_count} total):\n{rows_text}"


_LAST_SALE_QUESTION = re.compile(
    r"(últim[oa]|ultimo|last|most recent|latest).{0,80}(vendid|venta|sold)|"
    r"(vendid|venta|sold).{0,80}(últim[oa]|ultimo|last|más reciente|mas reciente)",
    re.IGNORECASE | re.DOTALL,
)


def _from_table(select: sqlglot.exp.Select) -> sqlglot.exp.Table | None:
    from_clause = select.find(sqlglot.exp.From)
    if from_clause is None:
        return None
    table = from_clause.this
    if isinstance(table, sqlglot.exp.Table):
        return table
    return None


def _sales_alias(select: sqlglot.exp.Select) -> str | None:
    for table in select.find_all(sqlglot.exp.Table):
        if table.name.lower() == "sales":
            return table.alias_or_name
    return None


def _order_has_root_id(select: sqlglot.exp.Select, alias: str) -> bool:
    order = select.args.get("order")
    if order is None:
        return False
    alias_l = alias.lower()
    for ordered in order.expressions:
        col = ordered.this
        if not isinstance(col, sqlglot.exp.Column):
            continue
        if col.name.lower() != "id":
            continue
        tbl = (col.table or "").lower()
        if not tbl or tbl == alias_l:
            return True
    return False


def _has_order_status_predicate(select: sqlglot.exp.Select) -> bool:
    for col in select.find_all(sqlglot.exp.Column):
        if col.name.lower() == "order_status":
            return True
    return False


def stabilize_sql(sql: str, question: str = "") -> str:
    """Hace determinista un SELECT con LIMIT: ORDER BY ... id DESC y ventas completed.

    Si el parseo falla, devuelve el SQL original.
    """
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return sql
    if not isinstance(parsed, sqlglot.exp.Select):
        return sql

    root = _from_table(parsed)
    alias = root.alias_or_name if root is not None else None
    if (
        alias
        and parsed.args.get("limit") is not None
        and parsed.args.get("order") is not None
        and not _order_has_root_id(parsed, alias)
    ):
        id_col = sqlglot.exp.Column(
            this=sqlglot.exp.to_identifier("id"),
            table=sqlglot.exp.to_identifier(alias),
        )
        parsed.args["order"].append(
            "expressions",
            sqlglot.exp.Ordered(this=id_col, desc=True),
        )

    if (
        question
        and _LAST_SALE_QUESTION.search(question)
        and _sales_alias(parsed)
        and not _has_order_status_predicate(parsed)
    ):
        sales_alias = _sales_alias(parsed)
        if sales_alias:
            parsed = parsed.where(
                sqlglot.exp.EQ(
                    this=sqlglot.exp.Column(
                        this=sqlglot.exp.to_identifier("order_status"),
                        table=sqlglot.exp.to_identifier(sales_alias),
                    ),
                    expression=sqlglot.exp.Literal.string("completed"),
                ),
                copy=False,
            )

    try:
        return parsed.sql(dialect="postgres")
    except Exception:
        return sql


_SQL_GENERATION_PROMPT = """You are a PostgreSQL SQL expert. Generate a valid, safe SQL query from the schema and question below.

## TABLE & COLUMN INVENTORY (every table with every column)
{schema}

## FOREIGN KEY CHAINS (how tables connect — use these to build JOINs)
{fk_chains}

## QUESTION
{question}

## HOW TO REASON
1. Identify which table(s) contain the data the user is asking about.
2. If the answer requires data from multiple tables, FOLLOW THE FK CHAINS above.
   Example: "sales by category" → sales.product_id → products.id → products.category_id → categories.id
3. NEVER guess table or column names — only use what's listed in the inventory.
4. For aggregations (total, sum, count, average) use GROUP BY on the entity name.
5. For "last / most recent / latest" use ORDER BY date_column DESC, id DESC LIMIT 1.
   Never ORDER BY a timestamp alone: ties make LIMIT 1 non-deterministic.
6. For questions about sold / last sale / "último vendido" on sales, add
   order_status = 'completed' (exclude cancelled and refunded).
7. For date ranges use >= and <= (not BETWEEN with timestamps).
8. For text search use ILIKE '%term%' or LOWER(col) = LOWER('term').
9. If no LIMIT present and the query could return many rows, add LIMIT 50.
10. ONLY SELECT. Never INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE.

## CRITICAL — USER-FACING OUTPUT RULES
11. NEVER select raw ID columns (id, UUID, *_id) in the final output. Use JOINs to resolve them to human-readable names.
    ORDER BY table_alias.id DESC is required for stable LIMIT; do not SELECT that id.
12. ALWAYS include the "name" column (or equivalent display name) when selecting from any entity table.
13. Prefer: SELECT p.name AS producto, c.name AS categoria, p.price
    NOT:    SELECT p.id, p.category_id, p.price
14. For products specifically, always SELECT: name, price, active_ingredient, concentration, presentation_unit.
    Never SELECT: id, sku, registration_number, cost, slug.

## OUTPUT FORMAT
Return ONLY the SQL statement. No markdown, no explanation, no backticks, no prefix.
If the question CANNOT be answered with this schema, respond with exactly: NO_QUERY

## SQL:"""


_DETERMINISTIC_FORMAT_PROMPT = """You are formatting database query results into a natural language answer.

## ORIGINAL QUESTION
{question}

## SQL EXECUTED
{sql}

## QUERY RESULTS (THIS IS THE ONLY SOURCE OF TRUTH)
{results}

## ADDITIONAL CONTEXT (for supplementary details like product descriptions)
{context}

## CRITICAL RULES
1. The query results above ARE the answer. Format them, don't invent.
2. NEVER add data, numbers, dates, or facts not present in the results.
3. If results are empty (0 rows), say exactly: "No se encontraron resultados para tu consulta."
4. Format numbers: use thousand separators and currency symbols from context.
5. Respond in the same language as the question.
6. Use the additional context ONLY for supplementary descriptions (what a product is, policies, etc.).
   Never use context to override or supplement the hard data from query results.
7. Be concise. If the results are a single row, state it directly.

## ANSWER:"""


class PostgresSqlExpert(SqlExpert):
    """Implementación de SqlExpert usando PostgreSQL + LLM."""

    SYSTEM_SCHEMAS = SYSTEM_SCHEMAS
    SYSTEM_TABLES = SYSTEM_TABLES

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def _discover_sources(self, tenant_id: UUID) -> list[DataSource]:
        session: AsyncSession = await get_async_session()
        try:
            return await fetch_sources(session)
        finally:
            await session.close()

    async def _discover_columns(
        self, session: AsyncSession, schema: str, table: str
    ) -> list[ColumnMeta]:
        return await fetch_columns(session, schema, table)

    def _build_schema_context(self, sources: list[DataSource], role: str) -> dict[str, str]:
        """Construye el inventario de tablas y cadenas FK para el LLM."""
        lines: list[str] = []
        fk_pairs: list[tuple[str, str, str, str, str]] = []  # (from_table, from_col, to_table, to_col, from_full)

        for s in sources:
            cols = []
            for c in s.columns:
                parts = [c.name, f"({c.data_type})"]
                if c.is_primary_key:
                    parts.append("PK")
                if c.is_foreign_key:
                    parts.append("FK")
                    fk_pairs.append((
                        f"{s.schema_name}.{s.table_name}",
                        c.name,
                        c.fk_table or "?",
                        c.fk_column or "?",
                        f"{s.schema_name}.{s.table_name}.{c.name}",
                    ))
                cols.append(" ".join(parts))
            is_view_mark = " [VIEW]" if s.is_view else ""
            lines.append(
                f"{s.schema_name}.{s.table_name}{is_view_mark}"
                f" ({s.row_count} rows)"
                f"\n  {', '.join(cols)}"
            )

        schema_inventory = "\n\n".join(lines)

        # Build FK chain visualization
        fk_chain_lines: list[str] = []
        if fk_pairs:
            # Group by target table to show chains
            for from_tbl, from_col, to_tbl, to_col, from_full in fk_pairs:
                fk_chain_lines.append(
                    f"  {from_full} → {to_tbl}.{to_col}"
                )
            # Add multi-hop examples if we have chains
            chains = self._find_fk_chains(fk_pairs)
            if chains:
                fk_chain_lines.append("\n  Multi-hop chains available:")
                for chain in chains:
                    fk_chain_lines.append(f"    {' → '.join(chain)}")

        fk_chains_text = "\n".join(fk_chain_lines) if fk_chain_lines else "  (no foreign keys detected)"

        role_block = ""
        if role == "customer":
            role_block = (
                "\n\nIMPORTANT: You are answering for a customer.\n"
                "Do NOT use GROUP BY, SUM(), COUNT(), AVG() for aggregations across all rows.\n"
                "Only return this customer's own data."
            )

        return {
            "schema": schema_inventory + role_block,
            "fk_chains": fk_chains_text,
            "role_block": role_block,
        }

    def _find_fk_chains(self, fk_pairs: list[tuple]) -> list[list[str]]:
        """Find multi-hop FK chains: sales → products → categories."""
        chains: list[list[str]] = []
        # Build a graph: from_table → [(to_table, edge_label)]
        graph: dict[str, list[tuple[str, str]]] = {}
        seen_edges = set()
        for from_tbl, _from_col, to_tbl, _to_col, edge_label in fk_pairs:
            key = (from_tbl, to_tbl)
            if key not in seen_edges:
                seen_edges.add(key)
                graph.setdefault(from_tbl, []).append((to_tbl, edge_label or f"{from_tbl}→{to_tbl}"))

        # Find chains of depth 2+
        for start_node in list(graph.keys()):
            visited: set[str] = set()
            path: list[str] = [start_node]
            self._dfs_chains(graph, start_node, path, visited, chains)

        return chains[:5]  # Max 5 chains to avoid prompt bloat

    def _dfs_chains(
        self,
        graph: dict[str, list[tuple[str, str]]],
        current: str,
        path: list[str],
        visited: set[str],
        chains: list[list[str]],
        depth: int = 2,
    ) -> None:
        if len(path) >= 3 and depth >= 2:
            chains.append(list(path))
        if current not in graph:
            return
        for next_node, _edge_label in graph[current]:
            if next_node not in path and next_node not in visited:
                visited.add(next_node)
                path.append(next_node)
                self._dfs_chains(graph, next_node, path, visited, chains, depth + 1)
                path.pop()
                visited.discard(next_node)

    async def execute(
        self,
        tenant_id: UUID,
        question: str,
        role: str,
    ) -> SqlQueryResult:
        sources = await self._discover_sources(tenant_id)
        schema_ctx = self._build_schema_context(sources, role)

        prompt = _SQL_GENERATION_PROMPT.format(
            schema=schema_ctx["schema"],
            fk_chains=schema_ctx["fk_chains"],
            question=question,
        )

        try:
            llm_response = await self._llm.generate(
                prompt=prompt,
                max_tokens=512,
                temperature=0.0,
            )
        except Exception as exc:
            logger.error("LLM SQL generation failed", error=str(exc))
            return SqlQueryResult(sql="", error=f"LLM error: {exc}")

        sql = llm_response.content.strip()
        if not sql or sql.upper().startswith("NO_QUERY"):
            return SqlQueryResult(sql="", error="Cannot generate query for this question")

        sql = self._clean_sql(sql)
        sql = stabilize_sql(sql, question)

        try:
            await self.validate_sql(sql, sources, role)
        except SqlValidationError as exc:
            return SqlQueryResult(sql=sql, error=str(exc))

        return await self._run_query(sql)

    async def format_results(
        self,
        question: str,
        sql: str,
        sql_result: SqlQueryResult,
        context_snippets: str = "",
    ) -> str:
        """Formatea resultados SQL en lenguaje natural usando el LLM (modo determinista)."""
        if sql_result.error:
            return f"No se pudo ejecutar la consulta: {sql_result.error}"

        if sql_result.row_count == 0:
            return "No se encontraron resultados para tu consulta."

        formatted = _format_sql_result(sql_result, question)
        prompt = _DETERMINISTIC_FORMAT_PROMPT.format(
            question=question,
            sql=sql,
            results=formatted,
            context=context_snippets or "(no additional context available)",
        )

        try:
            llm_response = await self._llm.generate(
                prompt=prompt,
                max_tokens=1024,
                temperature=0.1,
            )
            return llm_response.content
        except Exception as exc:
            logger.error("SQL result formatting failed", error=str(exc))
            return formatted

    def _clean_sql(self, sql: str) -> str:
        sql = sql.strip().rstrip(";")
        if sql.startswith("```"):
            sql = re.sub(r"^```\w*\n?", "", sql)
            sql = re.sub(r"\n?```$", "", sql)
        return sql.strip()

    async def validate_sql(
        self,
        sql: str,
        sources: list[DataSource],
        role: str,
    ) -> None:
        _validate_sql_ast(sql)

        if _FORBIDDEN_KEYWORDS.search(sql):
            raise SqlValidationError("Forbidden SQL keyword detected", sql)

        if role == "customer":
            upper = sql.upper()
            forbidden = ["GROUP BY", "COUNT(", "SUM(", "AVG(", "MIN(", "MAX("]
            for kw in forbidden:
                if kw in upper:
                    raise SqlValidationError(
                        f"Cannot use {kw.strip('(')}() as customer", sql
                    )

        valid_tables = {
            f"{s.schema_name}.{s.table_name}".lower() for s in sources
        }
        valid_tables |= {s.table_name.lower() for s in sources}
        valid_columns: set[str] = set()
        for s in sources:
            for c in s.columns:
                valid_columns.add(c.name.lower())

        table_refs = set(re.findall(r'"(\w+)"\."(\w+)"', sql))
        table_refs |= set((m,) for m in re.findall(r'\bFROM\s+(\w+)', sql, re.IGNORECASE))
        table_refs |= set((m,) for m in re.findall(r'\bJOIN\s+(\w+)', sql, re.IGNORECASE))

        # Validate via EXPLAIN instead of regex — catches all invalid refs
        await self._explain_validate(sql)

    async def _explain_validate(self, sql: str) -> None:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(text(f"EXPLAIN {sql}"))
        except Exception as exc:
            raise SqlValidationError(f"Invalid SQL: {exc}", sql) from exc
        finally:
            await session.close()

    async def _run_query(self, sql: str) -> SqlQueryResult:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(text("SET LOCAL statement_timeout = '5s'"))
            if not re.search(r"\bLIMIT\s+\d+\s*$", sql, re.IGNORECASE):
                sql = f"{sql} LIMIT 100"
            rows_result = await session.execute(text(sql))
            rows = rows_result.fetchall()
            columns = list(rows_result.keys()) if rows else []
            return SqlQueryResult(
                sql=sql,
                columns=columns,
                rows=[[str(v) for v in row] for row in rows],
                row_count=len(rows),
            )
        except Exception as exc:
            return SqlQueryResult(sql=sql, error=str(exc))
        finally:
            await session.close()

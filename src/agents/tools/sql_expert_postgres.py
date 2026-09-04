from __future__ import annotations

import asyncio
import importlib
import re
import time
from collections.abc import Callable
from uuid import UUID

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.tools.schema_relevance import SchemaCache, build_relevant_schema
from src.connectors.sql.schema_discovery import (
    SYSTEM_SCHEMAS,
    SYSTEM_TABLES,
)
from src.connectors.sql.schema_discovery import (
    discover_columns as fetch_columns,
)
from src.connectors.sql.schema_discovery import (
    discover_sources as fetch_sources,
)
from src.core.config import get_settings
from src.core.domain.services import ColumnMeta, DataSource
from src.core.ports import CacheProvider, LLMProvider
from src.core.ports.sql_expert import SqlExpert, SqlQueryResult, SqlValidationError
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

# Audit table ensure: una vez por proceso (idempotente, race benigna).
_AUDIT_TABLE_ENSURED = False

# Palabras prohibidas en SQL — prevención de inyección estructural
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE"
    r"|EXECUTE|GRANT|REVOKE|COPY|VACUUM|REINDEX|INTO"
    r"|SET\s+role|RESET\s+role|SET\s+SESSION|SET\s+LOCAL"
    r"|pg_read_file|pg_write_file|pg_read_binary_file|pg_ls_dir"
    r"|lo_import|lo_export|lo_get|dblink|set_config|pg_terminate_backend"
    r"|pg_sleep|current_setting)\b"
    r"|\bFOR\s+(SHARE|UPDATE|KEY\s+SHARE|NO\s+KEY\s+UPDATE)\b",
    re.IGNORECASE,
)


_READ_ONLY_STATEMENTS = {"select", "describe"}

# Pistas de fallo de conexión del pool read-only. Se detectan ANTES de
# etiquetarlos como "Invalid SQL" para no enmascarar problemas de
# provisionamiento del rol (POSTGRES_READONLY_USER / 09-readonly-role.sh).
_CONNECTION_ERROR_HINTS = (
    "password authentication failed",
    "role ",
    "does not exist",
    "connection refused",
    "could not connect",
    "connection is closed",
    "connection reset",
    "ssl error",
    "server does not support ssl",
    "timeout expired",
    "connection timed out",
)


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

    if len(statements) > 1:
        raise SqlValidationError("Multi-statement SQL is not allowed", sql)

    for stmt in statements:
        stmt_type = stmt.key.lower() if stmt.key else "unknown"
        if stmt_type not in _READ_ONLY_STATEMENTS:
            raise SqlValidationError(
                f"Only SELECT statements allowed, found: {stmt_type}", sql
            )

        _check_ctes(stmt, sql)

        _check_subqueries(stmt, sql)


def rewrite_organization_id_literals(expr: sqlglot.Expression, organization_id: UUID) -> None:
    """Reemplaza CUALQUIER `organization_id = <literal>` por el UUID autenticado.

    Un predicado escrito por el LLM (otro tenant) no se respeta: se reescribe.
    """
    auth = sqlglot.parse_one(f"'{organization_id}'::uuid")

    def _is_org_col(node: sqlglot.exp.Expression | None) -> bool:
        return isinstance(node, sqlglot.exp.Column) and node.name.lower() == "organization_id"

    for eq in list(expr.find_all(sqlglot.exp.EQ)):
        left, right = eq.left, eq.right
        if _is_org_col(left):
            eq.set("expression", auth.copy())
        elif _is_org_col(right):
            eq.set("this", auth.copy())


def rewrite_sql_organization_id(sql: str, organization_id: UUID) -> str:
    """Reescribe literales organization_id en un SQL (admin console / tests)."""
    try:
        expr = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
    except Exception:
        return sql
    rewrite_organization_id_literals(expr, organization_id)
    return expr.sql()


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


# -----------------------------------------------------------------------------
# Heuristics registry — heurísticas verticales configurables (pluggable)
# -----------------------------------------------------------------------------
HeuristicFn = Callable[[str, sqlglot.exp.Select], sqlglot.exp.Select | None]

_SQL_HEURISTICS: list[tuple[str, HeuristicFn]] = []
_HEURISTICS_LOADED = False


def register_sql_heuristic(name: str, fn: HeuristicFn) -> None:
    """Registra una heurística de reescritura SQL (usada por verticals)."""
    if not any(existing == name for existing, _ in _SQL_HEURISTICS):
        _SQL_HEURISTICS.append((name, fn))


def load_sql_heuristics(module_paths: list[str] | None = None) -> None:
    """Carga heurísticas desde módulos verticales (cada módulo llama register())."""
    global _HEURISTICS_LOADED
    if _HEURISTICS_LOADED and module_paths is None:
        return
    paths = module_paths
    if paths is None:
        paths = [
            p.strip()
            for p in get_settings().SQL_HEURISTICS_MODULES.split(",")
            if p.strip()
        ]
    for path in paths:
        try:
            module = importlib.import_module(path)
            register = getattr(module, "register", None)
            if callable(register):
                register()
            logger.info("Loaded SQL heuristics module", module=path)
        except Exception as exc:
            logger.warning(
                "Failed to load SQL heuristics module",
                module=path,
                error=str(exc),
            )
    _HEURISTICS_LOADED = True


def _from_table(select: sqlglot.exp.Select) -> sqlglot.exp.Table | None:
    from_clause = select.find(sqlglot.exp.From)
    if from_clause is None:
        return None
    table = from_clause.this
    if isinstance(table, sqlglot.exp.Table):
        return table
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


def stabilize_sql(sql: str, question: str = "") -> str:
    """Hace determinista un SELECT con LIMIT: ORDER BY ... id DESC.

    Aplica además las heurísticas registradas por verticales (pluggable).
    Si el parseo falla, devuelve el SQL original.
    """
    if not _HEURISTICS_LOADED:
        load_sql_heuristics()
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
        and parsed.args.get("group") is None  # aggregates no pueden ordenar por s.id
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

    if question:
        for _name, heuristic in _SQL_HEURISTICS:
            try:
                rewritten = heuristic(question, parsed)
                if rewritten is not None:
                    parsed = rewritten
            except Exception as exc:
                logger.warning("SQL heuristic failed", error=str(exc))

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
6. For questions about sold / last sale / "último vendido" on a sales-like
   table, follow the filtering rules provided in the inventory (if any).
7. For date ranges use >= and <= (not BETWEEN with timestamps).
8. For text search use ILIKE '%term%' or LOWER(col) = LOWER('term').
9. If no LIMIT present and the query could return many rows, add LIMIT 50.
10. ONLY SELECT. Never INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE.
11. JOIN TYPE SAFETY: never CAST ID columns to UUID or vice versa. If a
    *_id column is VARCHAR/text (it stores external keys), join it against
    the matching VARCHAR column (usually *_external_id / external_id), NOT
    against the uuid primary key. Match types exactly.

## CRITICAL — USER-FACING OUTPUT RULES
12. NEVER select raw ID columns (id, UUID, *_id) in the final output. Use JOINs to resolve them to human-readable names.
    ORDER BY table_alias.id DESC is required for stable LIMIT; do not SELECT that id.
13. ALWAYS include the "name" column (or equivalent display name) when selecting from any entity table.
14. Prefer: SELECT p.name AS producto, c.name AS categoria, p.price
    NOT:    SELECT p.id, p.category_id, p.price
15. For entity tables, SELECT only user-readable business columns (display name,
    price, description...). Never SELECT technical columns (internal codes,
    costs, slugs, registration numbers).

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


_SQL_REPAIR_PROMPT = """You are a PostgreSQL SQL expert. Fix the invalid SQL below.

## TABLE & COLUMN INVENTORY (every table with every column)
{schema}

## QUESTION
{question}

## INVALID SQL
{sql}

## DATABASE ERROR
{error}

## HOW TO FIX
1. Ensure every column in ORDER BY is either aggregated or in GROUP BY.
2. If the query aggregates (GROUP BY / SUM / COUNT), include all non-aggregated
   selected and ordered columns in the GROUP BY.
3. NEVER guess table or column names — only use what's listed in the inventory.
4. NEVER select raw ID columns (id, UUID, *_id) in the final output.
5. ONLY SELECT. Never INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, TRUNCATE.
6. Keep the query's original intent.
7. JOIN TYPES: if the error mentions a type mismatch or an invalid uuid
   input, REMOVE the CAST and join the columns of the SAME type. A VARCHAR
   *_id column stores external keys: join it against the VARCHAR
   external_id column of the referenced table. Follow the REQUIRED FIX in
   the error message exactly.

## OUTPUT FORMAT
Return ONLY the corrected SQL statement. No markdown, no explanation, no backticks.
If it cannot be fixed, respond with exactly: NO_QUERY

## SQL:"""


class PostgresSqlExpert(SqlExpert):
    """Implementación de SqlExpert usando PostgreSQL + LLM."""

    SYSTEM_SCHEMAS = SYSTEM_SCHEMAS
    SYSTEM_TABLES = SYSTEM_TABLES

    def __init__(
        self,
        llm_provider: LLMProvider,
        cache: CacheProvider | None = None,
    ) -> None:
        self._llm = llm_provider
        self._last_cost: float | None = None
        self._permissions: dict | None = None
        settings = get_settings()
        self._schema_cache = (
            SchemaCache(cache, ttl_seconds=settings.RAG_SQL_SCHEMA_CACHE_TTL)
            if cache is not None
            else None
        )

    async def _discover_sources(self, organization_id: UUID) -> list[DataSource]:
        if self._schema_cache is not None:
            cached = await self._schema_cache.get(organization_id)
            if cached is not None:
                return cached
        session: AsyncSession = await get_async_session()
        try:
            sources = await fetch_sources(session)
            sources = self._filter_platform_sources(sources)
        finally:
            await session.close()
        if self._schema_cache is not None:
            await self._schema_cache.set(organization_id, sources)
        return sources

    @staticmethod
    def _filter_platform_sources(sources: list[DataSource]) -> list[DataSource]:
        """Excluye el schema de plataforma (public) del inventario del SQL Expert.

        public.* contiene tablas de la plataforma (organizations, api_keys,
        plans, usage_events, ...). El motor Text-to-SQL solo opera sobre
        schemas de negocio del tenant (no-public): las tablas de plataforma
        no deben llegar al prompt del LLM ni ser consultables.
        """
        return [s for s in sources if s.schema_name.lower() != "public"]

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
        organization_id: UUID,
        question: str,
        role: str,
        permissions: dict | None = None,
        user_id: UUID | None = None,
    ) -> SqlQueryResult:
        """Wrapper con medición de tiempo + auditoría (fail-silent)."""
        from src.agents.tools.sql_audit import ensure_sql_audit_table, write_sql_audit
        from src.platform.tenants.context import get_tenant_context

        ctx = get_tenant_context()
        if ctx is not None:
            organization_id = ctx.tenant_id

        start = time.perf_counter()
        result = await self._execute_inner(
            organization_id, question, role, permissions
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        if not result.sql and result.error:
            status = "no_query"
        elif result.error:
            status = "execution_error"
        else:
            status = "success"
        tables = self._extract_tables(result.sql)

        global _AUDIT_TABLE_ENSURED
        if not _AUDIT_TABLE_ENSURED:
            _AUDIT_TABLE_ENSURED = True
            try:
                await ensure_sql_audit_table()
            except Exception:
                _AUDIT_TABLE_ENSURED = False
        try:
            await write_sql_audit(
                organization_id=organization_id,
                user_id=user_id,
                role=role,
                question=question,
                generated_sql=result.sql,
                tables=tables,
                execution_time_ms=elapsed_ms,
                rows=result.row_count,
                cost=result.cost,
                status=status,
                error=result.error,
            )
        except Exception:
            pass

        return result

    async def _execute_inner(
        self,
        organization_id: UUID,
        question: str,
        role: str,
        permissions: dict | None,
    ) -> SqlQueryResult:
        self._permissions = permissions
        all_sources = await self._discover_sources(organization_id)

        # Schema intelligence: solo el subconjunto relevante va al LLM.
        settings = get_settings()
        sources = build_relevant_schema(
            question, all_sources, max_tables=settings.RAG_SQL_MAX_TABLES
        )
        if not sources:
            return SqlQueryResult(
                sql="",
                error="Cannot generate query for this question",
            )

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
            safe_sql = await self.validate_sql(sql, sources, role, organization_id)
        except SqlValidationError as exc:
            repaired = await self._repair_sql(
                schema=schema_ctx["schema"],
                fk_chains=schema_ctx["fk_chains"],
                question=question,
                sql=sql,
                error=str(exc),
            )
            if repaired is not None:
                repaired = self._clean_sql(repaired)
                repaired = stabilize_sql(repaired, question)
                try:
                    safe_sql = await self.validate_sql(
                        repaired, sources, role, organization_id
                    )
                    logger.info(
                        "SQL repaired after validation failure",
                        original=sql[:300],
                        repaired=repaired[:300],
                    )
                    return await self._run_with_execution_repair(
                        safe_sql,
                        schema=schema_ctx["schema"],
                        fk_chains=schema_ctx["fk_chains"],
                        question=question,
                        sources=sources,
                        role=role,
                        organization_id=organization_id,
                    )
                except SqlValidationError as exc2:
                    logger.info(
                        "SQL repair failed validation",
                        sql=repaired[:300],
                        error=str(exc2),
                    )
                    return SqlQueryResult(sql=repaired, error=str(exc2))
            logger.info(
                "SQL failed validation, falling back",
                sql=sql[:300],
                error=str(exc),
            )
            return SqlQueryResult(sql=sql, error=str(exc))

        return await self._run_with_execution_repair(
            safe_sql,
            schema=schema_ctx["schema"],
            fk_chains=schema_ctx["fk_chains"],
            question=question,
            sources=sources,
            role=role,
            organization_id=organization_id,
        )

    async def _run_with_execution_repair(
        self,
        safe_sql: str,
        *,
        schema: str,
        fk_chains: str,
        question: str,
        sources: list[DataSource],
        role: str,
        organization_id: UUID,
    ) -> SqlQueryResult:
        """Ejecuta el SQL validado; si falla contra los datos, hasta 2 repairs."""
        result = await self._run_query(safe_sql)
        if result.error is None:
            return result

        current_sql = safe_sql
        last_error: str | None = result.error
        for _attempt in range(2):
            if last_error is None:
                break
            repaired = await self._repair_sql(
                schema=schema,
                fk_chains=fk_chains,
                question=question,
                sql=current_sql,
                error=last_error,
            )
            if repaired is None:
                return result
            repaired = self._clean_sql(repaired)
            repaired = stabilize_sql(repaired, question)
            try:
                safe_sql2 = await self.validate_sql(
                    repaired, sources, role, organization_id
                )
            except SqlValidationError as exc2:
                logger.info(
                    "SQL execution repair failed validation; retrying",
                    sql=repaired[:300],
                    error=str(exc2),
                )
                current_sql = repaired
                last_error = str(exc2)
                continue
            logger.info(
                "SQL repaired after execution failure",
                original=current_sql[:300],
                repaired=repaired[:300],
            )
            return await self._run_query(safe_sql2)

        return result

    async def _repair_sql(
        self,
        schema: str,
        fk_chains: str,
        question: str,
        sql: str,
        error: str,
    ) -> str | None:
        """Pide al LLM una corrección del SQL inválido (un solo intento)."""
        prompt = _SQL_REPAIR_PROMPT.format(
            schema=schema,
            question=question,
            sql=sql,
            error=error[:800],
        )
        try:
            llm_response = await self._llm.generate(
                prompt=prompt,
                max_tokens=512,
                temperature=0.0,
            )
        except Exception as exc:
            logger.error("LLM SQL repair failed", error=str(exc))
            return None
        repaired = llm_response.content.strip()
        if not repaired or repaired.upper().startswith("NO_QUERY"):
            return None
        return repaired

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

    # -------------------------------------------------------------------------
    # Organization isolation & table allowlist (enforced deterministically)
    # -------------------------------------------------------------------------

    @staticmethod
    def _table_identity(node: sqlglot.exp.Table) -> tuple[str, str]:
        """(schema, table) de un nodo Table; schema '' si no calificado."""
        schema = node.catalog or node.db or ""
        return str(schema).lower(), str(node.name).lower()

    @classmethod
    def _extract_tables(cls, sql: str) -> list[str]:
        """Tablas referenciadas por el SQL (para auditoría)."""
        if not sql:
            return []
        try:
            statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.RAISE)
        except Exception:
            return []
        tables: list[str] = []
        for stmt in statements:
            if stmt is None:
                continue
            for node in stmt.find_all(sqlglot.exp.Table):
                schema, table = cls._table_identity(node)
                if table and table not in tables:
                    tables.append(f"{schema}.{table}" if schema else table)
        return tables

    def _check_table_allowlist(
        self, sql: str, sources: list[DataSource]
    ) -> None:
        """Rechaza cualquier tabla fuera del inventario del organization.

        Bloquea en seco tablas de plataforma (users, api_keys, ...) y
        esquemas de otros organizations aunque existan en la BD.
        """
        sources_by_schema: dict[str, set[str]] = {}
        bare_owners: dict[str, set[str]] = {}
        for s in sources:
            sources_by_schema.setdefault(s.schema_name.lower(), set()).add(
                s.table_name.lower()
            )
            bare_owners.setdefault(s.table_name.lower(), set()).add(
                s.schema_name.lower()
            )

        statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.RAISE)
        for stmt in statements:
            for node in stmt.find_all(sqlglot.exp.Table):
                schema, table = self._table_identity(node)
                if schema:
                    if table not in sources_by_schema.get(schema, set()):
                        raise SqlValidationError(
                            f"Table '{schema}.{table}' is not available for this organization",
                            sql,
                        )
                else:
                    owners = bare_owners.get(table, set())
                    if not owners:
                        raise SqlValidationError(
                            f"Table '{table}' is not available for this organization",
                            sql,
                        )
                    if len(owners) > 1:
                        raise SqlValidationError(
                            f"Ambiguous table '{table}': qualify it with a schema",
                            sql,
                        )

    # ---------------------------------------------------------------------
    # JOIN type safety — determinista sobre la metadata del discovery
    # ---------------------------------------------------------------------
    @staticmethod
    def _normalize_type(data_type: str) -> str:
        t = data_type.lower()
        if t.startswith("character") or t in ("text", "varchar", "char"):
            return "string"
        if t == "uuid":
            return "uuid"
        return t

    def _check_join_types(self, sql: str, sources: list[DataSource]) -> None:
        """Rechaza JOINs con tipos incompatibles (uuid vs string) y sugiere fix.

        Guía determinista para el repair loop: si una columna *_id es
        VARCHAR (clave externa), el join debe ser contra la columna VARCHAR
        equivalente (p. ej. external_id), nunca contra el PK uuid.
        """
        # type map: (table, column) -> type normalizado
        col_types: dict[tuple[str, str], str] = {}
        for s in sources:
            for c in s.columns:
                normalized = self._normalize_type(c.data_type)
                col_types[(s.table_name.lower(), c.name.lower())] = normalized

        statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.RAISE)
        for stmt in statements:
            for select in stmt.find_all(sqlglot.exp.Select):
                alias_to_table: dict[str, str] = {}
                for table in self._direct_tables(select):
                    alias_to_table[table.alias_or_name.lower()] = table.name.lower()
                for join in select.args.get("joins") or []:
                    on = join.args.get("on")
                    if on is None:
                        continue
                    for eq in on.find_all(sqlglot.exp.EQ):
                        lhs, rhs = eq.this, eq.expression
                        left = self._column_ref_info(lhs, alias_to_table, col_types)
                        right = self._column_ref_info(rhs, alias_to_table, col_types)
                        if left is None or right is None:
                            continue
                        if left[0] == right[0]:
                            continue
                        if {left[0], right[0]} != {"uuid", "string"}:
                            continue
                        suggestion = self._join_type_suggestion(
                            left, right, col_types
                        )
                        raise SqlValidationError(
                            "JOIN type mismatch detected by the validator: "
                            f"{left[2]} ({left[0]}) is joined against "
                            f"{right[2]} ({right[0]}). "
                            f"REQUIRED FIX: {suggestion}. "
                            "Never CAST id columns across types; join columns "
                            "of the SAME type.",
                            sql,
                        )

    @staticmethod
    def _join_type_suggestion(
        left: tuple[str, str, str],
        right: tuple[str, str, str],
        col_types: dict[tuple[str, str], str],
    ) -> str:
        """Sugiere la columna del mismo tipo para arreglar el join."""
        ltype, ltable, lcol = left
        rtype, rtable, rcol = right
        if ltype == "string" and rtype == "uuid":
            candidates = [
                (c, t)
                for (tbl, c), t in col_types.items()
                if tbl == rtable and t == "string"
            ]
            preferred = [c for c, _ in candidates if "external" in c or c.endswith("_id") or c.endswith("_code")]
            pick = (preferred or [c for c, _ in candidates])[0] if candidates else None
            if pick:
                return f"join '{lcol}' against '{rtable}.{pick}' instead of the uuid column"
            return f"remove the uuid join on '{rtable}'"
        if ltype == "uuid" and rtype == "string":
            candidates = [
                (c, t)
                for (tbl, c), t in col_types.items()
                if tbl == ltable and t == "string"
            ]
            preferred = [c for c, _ in candidates if "external" in c or c.endswith("_id") or c.endswith("_code")]
            pick = (preferred or [c for c, _ in candidates])[0] if candidates else None
            if pick:
                return f"join '{rcol}' against '{ltable}.{pick}' instead of the uuid column"
            return f"remove the uuid join on '{ltable}'"
        return "match column types exactly"

    @staticmethod
    def _column_ref_info(
        expr: sqlglot.exp.Expression,
        alias_to_table: dict[str, str],
        col_types: dict[tuple[str, str], str],
    ) -> tuple[str, str, str] | None:
        """(tipo normalizado, tabla, columna) de una referencia, o None."""
        if isinstance(expr, sqlglot.exp.Cast):
            target = expr.args.get("to")
            target_type = target.sql() if target is not None else ""
            inner = expr.this
            inner_info = PostgresSqlExpert._column_ref_info(
                inner, alias_to_table, col_types
            )
            cast_type = PostgresSqlExpert._normalize_type(target_type)
            # CAST de columna string -> uuid es la fuente clásica de errores:
            # reportar el tipo ORIGINAL para detonar el repair.
            if inner_info is not None and inner_info[0] == "string" and cast_type == "uuid":
                return inner_info
            if inner_info is not None:
                return (cast_type, inner_info[1], inner_info[2])
            return None
        if isinstance(expr, sqlglot.exp.Column):
            table = (expr.table or "").lower()
            name = expr.name.lower()
            resolved_table = alias_to_table.get(table, table)
            col_type = col_types.get((resolved_table, name))
            if col_type is not None:
                return (col_type, resolved_table, name)
        return None

    @staticmethod
    def _direct_tables(select: sqlglot.exp.Select) -> list[sqlglot.exp.Table]:
        """Tablas referenciadas directamente por este SELECT (sin subqueries)."""
        tables: list[sqlglot.exp.Table] = []
        from_clause = select.args.get("from_")  # sqlglot >= 30 usa 'from_'
        if from_clause is not None and isinstance(from_clause.this, sqlglot.exp.Table):
            tables.append(from_clause.this)
        for join in select.args.get("joins") or []:
            if isinstance(join.this, sqlglot.exp.Table):
                tables.append(join.this)
        return tables

    @staticmethod
    def _where_condition(expr: sqlglot.exp.Expression | None) -> sqlglot.exp.Expression | None:
        """Extrae la condición interna de un nodo Where (o devuelve la expresión)."""
        if expr is None:
            return None
        if isinstance(expr, sqlglot.exp.Where):
            return expr.this
        return expr

    def _inject_organization_filter(
        self, sql: str, organization_id: UUID, sources: list[DataSource]
    ) -> str:
        """Inyecta `organization_id = '<tid>'::uuid` en tablas organization-aware.

        Reescritura determinística por AST. Si el LLM ya escribió un predicado
        organization_id (incluido otro UUID), se SOBREESCRIBE con el tenant
        autenticado y se inyecta el filtro calificado por tabla si falta.
        """
        organization_aware: set[str] = {
            f"{s.schema_name}.{s.table_name}".lower()
            for s in sources
            if any(c.name == "organization_id" for c in s.columns)
        }
        if not organization_aware:
            return sql

        bare_aware: set[str] = {t.split(".", 1)[-1] for t in organization_aware}

        expr = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
        targets: list[tuple[sqlglot.exp.Select, str]] = []
        for select in expr.find_all(sqlglot.exp.Select):
            for table in self._direct_tables(select):
                schema, name = self._table_identity(table)
                if name not in bare_aware:
                    continue
                if schema and f"{schema}.{name}" not in organization_aware:
                    continue
                targets.append((select, table.alias_or_name))

        rewrite_organization_id_literals(expr, organization_id)
        auth = str(organization_id)

        for select, ref in targets:
            where = select.args.get("where")
            snapshot = where.sql() if where is not None else ""
            if re.search(
                rf"\b{re.escape(ref)}\.organization_id\s*=\s*'?{re.escape(auth)}",
                snapshot,
                re.IGNORECASE,
            ):
                continue
            pred_eq = sqlglot.parse_one(
                f"{ref}.organization_id = '{organization_id}'::uuid"
            )
            condition = self._where_condition(where)
            if condition is None:
                new_where: sqlglot.exp.Expression = sqlglot.exp.Where(this=pred_eq)
            else:
                new_where = sqlglot.exp.Where(
                    this=sqlglot.exp.and_(condition, pred_eq, copy=False)
                )
            select.set("where", new_where)

        return expr.sql()

    @staticmethod
    def _cap_limit(sql: str, max_limit: int = 500) -> str:
        """Recorta cualquier LIMIT > max_limit en el SQL parseado."""
        try:
            expr = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
        except Exception:
            return sql
        for limit_node in expr.find_all(sqlglot.exp.Limit):
            raw = limit_node.expression
            if raw is None:
                continue
            try:
                value = int(raw.name)
            except (ValueError, TypeError):
                continue
            if value > max_limit:
                limit_node.set("expression", sqlglot.exp.Literal.number(max_limit))
        return expr.sql()

    @staticmethod
    def _check_cartesian_joins(sql: str) -> None:
        """Rechaza joins cartesianos: JOIN sin ON/USING o ON que no
        referencia columnas de AMBAS tablas."""
        try:
            expr = sqlglot.parse_one(sql, error_level=sqlglot.ErrorLevel.RAISE)
        except Exception:
            return

        for select in expr.find_all(sqlglot.exp.Select):
            for join in select.args.get("joins") or []:
                if isinstance(join.this, sqlglot.exp.Table):
                    table_name = join.this.alias_or_name.lower()
                    on = join.args.get("on")
                    if on is None and not join.args.get("using"):
                        raise SqlValidationError(
                            f"CROSS JOIN without ON is not allowed (table '{table_name}')",
                            sql,
                        )
                    if on is None:
                        continue
                    # El ON debe referenciar columnas de al menos 2 tablas
                    # distintas. Referencias sin calificar (sin alias) se
                    # permiten: no podemos verificarlas de forma determinista.
                    tables_ref = {
                        c.table.lower()
                        for c in on.find_all(sqlglot.exp.Column)
                        if c.table
                    }
                    if tables_ref and len(tables_ref) < 2:
                        raise SqlValidationError(
                            "Cartesian join detected: ON condition must "
                            "reference columns from both sides",
                            sql,
                        )

    @staticmethod
    def _resolve_blocklist(
        permissions: dict | None,
        role: str,
    ) -> tuple[set[str], set[str]]:
        """(columnas bloqueadas, tablas bloqueadas) para el rol.

        Precedencia: config_json del tenant sobre defaults globales.
        """
        settings = get_settings()
        global_cols = {
            c.strip().lower()
            for c in settings.RAG_SQL_SENSITIVE_COLUMNS.split(",")
            if c.strip()
        }
        global_tables: set[str] = set()
        if permissions and isinstance(permissions, dict):
            role_blocklist = (permissions.get("column_blocklist") or {}).get(
                role, []
            )
            global_cols.update(c.lower() for c in role_blocklist)
            global_tables.update(
                t.lower() for t in permissions.get("table_blocklist") or []
            )
        return global_cols, global_tables

    def _check_permissions(
        self,
        sql: str,
        role: str,
        permissions: dict | None,
    ) -> None:
        """Permission check determinístico: columnas y tablas bloqueadas."""
        column_blocklist, table_blocklist = self._resolve_blocklist(
            permissions, role
        )
        if not column_blocklist and not table_blocklist:
            return

        statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.RAISE)
        for stmt in statements:
            if stmt is None:
                continue
            for node in stmt.find_all(sqlglot.exp.Table):
                schema, table = self._table_identity(node)
                if table in table_blocklist:
                    raise SqlValidationError(
                        f"Table '{table}' is blocked for role '{role}'", sql
                    )
            for col in stmt.find_all(sqlglot.exp.Column):
                if col.name.lower() in column_blocklist:
                    raise SqlValidationError(
                        f"Column '{col.name}' is blocked for role '{role}'",
                        sql,
                    )

    async def validate_sql(
        self,
        sql: str,
        sources: list[DataSource],
        role: str,
        organization_id: UUID,
    ) -> str:
        """Valida y reescribe el SQL generado por el LLM.

        Retorna el SQL seguro a ejecutar (organization-filtered + LIMIT capped).
        """
        settings = get_settings()
        permissions = getattr(self, "_permissions", None)
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

        # Allowlist determinística de tablas (no regex, no dead code).
        self._check_table_allowlist(sql, sources)

        # Chequeo determinista de tipos en JOINs (guidance para el repair).
        self._check_join_types(sql, sources)

        # Query planner: sin joins cartesianos.
        self._check_cartesian_joins(sql)

        # Permission check por rol (blocklist de columnas/tablas).
        self._check_permissions(sql, role, permissions)

        # Aislamiento multi-organization: inyectar predicado organization_id.
        safe_sql = self._inject_organization_filter(sql, organization_id, sources)

        # Cap de filas: LIMIT <= RAG_SQL_MAX_ROWS.
        safe_sql = self._cap_limit(safe_sql, max_limit=settings.RAG_SQL_MAX_ROWS)

        # Validate via EXPLAIN (con timeout) + costo máximo del plan.
        await self._explain_validate(safe_sql)

        return safe_sql

    async def _explain_validate(self, sql: str) -> float | None:
        """EXPLAIN (FORMAT JSON) con timeout; bloquea si el costo del plan
        excede RAG_SQL_MAX_COST. Nunca ejecuta la query. Retorna el costo."""
        settings = get_settings()
        timeout_seconds = settings.RAG_SQL_TIMEOUT_SECONDS
        max_cost = settings.RAG_SQL_MAX_COST
        from src.infrastructure.postgres.readonly_session import get_readonly_session

        session = await get_readonly_session()
        try:
            from src.infrastructure.postgres.readonly_session import apply_readonly_transaction

            await apply_readonly_transaction(session, timeout_seconds)
            result = await asyncio.wait_for(
                session.execute(text(f"EXPLAIN (FORMAT JSON) {sql}")),
                timeout=float(timeout_seconds),
            )
            row = result.fetchone()
            if row is None:
                raise SqlValidationError("EXPLAIN returned no plan", sql)
            plan_json = row[0]
            total_cost = self._extract_total_cost(plan_json)
            self._last_cost = total_cost
            if total_cost is not None and total_cost > max_cost:
                raise SqlValidationError(
                    "Query plan too expensive: "
                    f"estimated cost {total_cost:.1f} exceeds "
                    f"limit {max_cost:.1f}",
                    sql,
                )
            return total_cost
        except SqlValidationError:
            raise
        except Exception as exc:
            if any(hint in str(exc).lower() for hint in _CONNECTION_ERROR_HINTS):
                logger.error(
                    "SQL Expert: read-only database connection failed. "
                    "Verify POSTGRES_READONLY_USER / POSTGRES_READONLY_PASSWORD "
                    "and run db_init/09-readonly-role.sh on existing volumes.",
                    error=str(exc),
                    sql=sql[:300],
                )
            else:
                logger.warning("SQL Expert: EXPLAIN validation failed", error=str(exc))
            raise SqlValidationError(f"Invalid SQL: {exc}", sql) from exc
        finally:
            await session.close()

    @staticmethod
    def _extract_total_cost(plan_json) -> float | None:
        """Extrae Total Cost del plan JSON de EXPLAIN (raíz)."""
        import json as _json

        try:
            if isinstance(plan_json, str):
                data = _json.loads(plan_json)
            else:
                data = plan_json
            plans = data if isinstance(data, list) else [data]
            root = plans[0]
            plan = root.get("Plan") or root
            raw = plan.get("Total Cost")
            if raw is None:
                return None
            return float(raw)
        except Exception:
            return None

    async def _run_query(self, sql: str) -> SqlQueryResult:
        settings = get_settings()
        timeout_seconds = settings.RAG_SQL_TIMEOUT_SECONDS
        max_rows = settings.RAG_SQL_MAX_ROWS
        cost = getattr(self, "_last_cost", None)
        from src.infrastructure.postgres.readonly_session import get_readonly_session

        session = await get_readonly_session()
        try:
            from src.infrastructure.postgres.readonly_session import apply_readonly_transaction

            await apply_readonly_transaction(session, timeout_seconds)
            if not re.search(r"\bLIMIT\s+\d+\s*$", sql, re.IGNORECASE):
                sql = f"{sql} LIMIT {max_rows}"
            rows_result = await asyncio.wait_for(
                session.execute(text(sql)),
                timeout=float(timeout_seconds),
            )
            rows = rows_result.fetchall()
            columns = list(rows_result.keys()) if rows else []
            truncated = len(rows) >= max_rows
            return SqlQueryResult(
                sql=sql,
                columns=columns,
                rows=[[str(v) for v in row] for row in rows],
                row_count=len(rows),
                truncated=truncated,
                cost=cost,
            )
        except Exception as exc:
            return SqlQueryResult(sql=sql, error=str(exc), cost=cost)
        finally:
            await session.close()

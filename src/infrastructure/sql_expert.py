from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports import LLMProvider
from src.domain.services import ColumnMeta, DataSource
from src.domain.sql_expert import SqlExpert, SqlQueryResult, SqlValidationError
from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import get_async_session

logger = get_logger(__name__)

# Palabras prohibidas en SQL — prevención de inyección estructural
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE"
    r"|EXECUTE|GRANT|REVOKE|COPY|VACUUM|REINDEX"
    r"|SET\s+role|RESET\s+role|pg_read_file|pg_write_file"
    r"|lo_import|lo_export)\b",
    re.IGNORECASE,
)

_SQL_GENERATION_PROMPT = """You are a PostgreSQL SQL expert. Given a database schema and a user question, generate a valid, safe SQL query.

Rules — violation will be rejected:
1. ONLY SELECT statements. Never INSERT, UPDATE, DELETE, DROP, etc.
2. Use ONLY tables and columns listed in the schema. Do not invent names.
3. Use explicit JOINs based on foreign keys documented below.
4. For text search in strings, use ILIKE or LOWER(col) = LOWER('value').
5. Always add LIMIT 50 if the query has no LIMIT and could return multiple rows.
6. Never include user input directly as a column or table name.
7. Return ONLY the SQL statement. No markdown, no explanation, no prefix.
8. If you CANNOT answer with the available schema, respond with exactly: NO_QUERY

Available schema:
{schema}

User question: {question}

SQL:"""


class PostgresSqlExpert(SqlExpert):
    """Implementación de SqlExpert usando PostgreSQL + LLM."""

    SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}
    SYSTEM_TABLES = {
        "tenants", "users", "rate_limit_counters", "usage_logs",
        "query_audit_log", "documents", "alembic_version",
    }

    def __init__(self, llm_provider: LLMProvider) -> None:
        self._llm = llm_provider

    async def _discover_sources(self, tenant_id: UUID) -> list[DataSource]:
        session: AsyncSession = await get_async_session()
        try:
            rows = await session.execute(
                text(
                    "SELECT table_schema, table_name, table_type "
                    "FROM information_schema.tables "
                    "WHERE table_type IN ('BASE TABLE', 'VIEW') "
                    "AND table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast') "
                    "AND table_name NOT IN ("
                    "  'tenants', 'users', 'rate_limit_counters', 'usage_logs', "
                    "  'query_audit_log', 'documents', 'alembic_version'"
                    ") ORDER BY table_schema, table_name"
                )
            )
            sources: list[DataSource] = []
            for schema_name, table_name, table_type in rows.fetchall():
                cols = await self._discover_columns(session, schema_name, table_name)
                count_r = await session.execute(
                    text(f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"')
                )
                sources.append(DataSource(
                    schema_name=schema_name,
                    table_name=table_name,
                    columns=cols,
                    row_count=count_r.scalar() or 0,
                    is_view=(table_type == "VIEW"),
                ))
            return sources
        finally:
            await session.close()

    async def _discover_columns(
        self, session: AsyncSession, schema: str, table: str
    ) -> list[ColumnMeta]:
        rows = await session.execute(
            text(
                "SELECT c.column_name, c.data_type, c.is_nullable, "
                "  CASE WHEN pk.column_name IS NOT NULL THEN true ELSE false END AS is_pk, "
                "  CASE WHEN fk.column_name IS NOT NULL THEN true ELSE false END AS is_fk, "
                "  fk.foreign_table_name AS fk_table, "
                "  fk.foreign_column_name AS fk_column "
                "FROM information_schema.columns c "
                "LEFT JOIN ("
                "  SELECT ku.table_schema, ku.table_name, ku.column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage ku "
                "    ON tc.constraint_name = ku.constraint_name "
                "  WHERE tc.constraint_type = 'PRIMARY KEY'"
                ") pk ON c.table_schema = pk.table_schema "
                "     AND c.table_name = pk.table_name "
                "     AND c.column_name = pk.column_name "
                "LEFT JOIN ("
                "  SELECT kcu.table_schema, kcu.table_name, kcu.column_name, "
                "    ccu.table_name AS foreign_table_name, "
                "    ccu.column_name AS foreign_column_name "
                "  FROM information_schema.table_constraints tc "
                "  JOIN information_schema.key_column_usage kcu "
                "    ON tc.constraint_name = kcu.constraint_name "
                "  JOIN information_schema.constraint_column_usage ccu "
                "    ON tc.constraint_name = ccu.constraint_name "
                "  WHERE tc.constraint_type = 'FOREIGN KEY'"
                ") fk ON c.table_schema = fk.table_schema "
                "     AND c.table_name = fk.table_name "
                "     AND c.column_name = fk.column_name "
                "WHERE c.table_schema = :schema AND c.table_name = :table "
                "ORDER BY c.ordinal_position"
            ),
            {"schema": schema, "table": table},
        )
        return [
            ColumnMeta(
                name=row.column_name,
                data_type=str(row.data_type),
                is_nullable=row.is_nullable == "YES",
                is_primary_key=row.is_pk,
                is_foreign_key=row.is_fk,
                fk_table=row.fk_table,
                fk_column=row.fk_column,
            )
            for row in rows.fetchall()
        ]

    def _build_schema_context(self, sources: list[DataSource], role: str) -> str:
        """Construye un resumen del schema para el LLM."""
        lines: list[str] = []
        fk_lines: list[str] = []

        for s in sources:
            cols = []
            for c in s.columns:
                parts = [c.name, f"({c.data_type})"]
                if c.is_primary_key:
                    parts.append("PK")
                if c.is_foreign_key:
                    parts.append(f"FK→{c.fk_table}.{c.fk_column}")
                    fk_lines.append(
                        f"  {s.schema_name}.{s.table_name}.{c.name}"
                        f" → {c.fk_table}.{c.fk_column}"
                    )
                cols.append(" ".join(parts))
            is_view_mark = " [VIEW]" if s.is_view else ""
            lines.append(
                f"Table: {s.schema_name}.{s.table_name}{is_view_mark}"
                f"  ({s.row_count} rows)"
                f"\n  Columns: {', '.join(cols)}"
            )

        if role == "customer" and fk_lines:
            lines.append("\nIMPORTANT: You are answering for a customer.")
            lines.append(
                "Do NOT use GROUP BY, SUM(), COUNT(), AVG() for"
                " aggregations across all rows."
            )
            lines.append("Only return this customer's own data.")

        if fk_lines:
            lines.insert(0, "Foreign Keys:\n" + "\n".join(fk_lines) + "\n")

        return "\n".join(lines)

    async def execute(
        self,
        tenant_id: UUID,
        question: str,
        role: str,
    ) -> SqlQueryResult:
        sources = await self._discover_sources(tenant_id)
        schema_ctx = self._build_schema_context(sources, role)

        prompt = _SQL_GENERATION_PROMPT.format(
            schema=schema_ctx, question=question,
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

        try:
            await self.validate_sql(sql, sources, role)
        except SqlValidationError as exc:
            return SqlQueryResult(sql=sql, error=str(exc))

        return await self._run_query(sql)

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
        if not sql.upper().startswith("SELECT"):
            raise SqlValidationError("Only SELECT statements allowed", sql)

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

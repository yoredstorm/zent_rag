# =============================================================================
# Schema Discovery — Shared PostgreSQL information_schema helpers
# =============================================================================
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.services import ColumnMeta, DataSource

SYSTEM_SCHEMAS = {"information_schema", "pg_catalog", "pg_toast"}
SYSTEM_TABLES = {
    "tenants",
    "users",
    "rate_limit_counters",
    "usage_logs",
    "query_audit_log",
    "documents",
    "alembic_version",
    "api_tokens",
    "subscriptions",
    "plans",
    "request_quota",
    "rag_evaluations",
}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_ident(name: str) -> str:
    """Quote a PostgreSQL identifier after validating it is a simple name."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return f'"{name}"'


async def discover_columns(session: AsyncSession, schema: str, table: str) -> list[ColumnMeta]:
    """Descubre columnas, tipos, PKs y FKs de una tabla."""
    rows = await session.execute(
        text(
            "SELECT "
            "  c.column_name, c.data_type, c.is_nullable, "
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


async def discover_sources(session: AsyncSession) -> list[DataSource]:
    """Descubre tablas y vistas indexables (excluye esquemas/tablas de sistema)."""
    excluded = "', '".join(sorted(SYSTEM_TABLES))
    rows = await session.execute(
        text(
            "SELECT table_schema, table_name, table_type "
            "FROM information_schema.tables "
            "WHERE table_type IN ('BASE TABLE', 'VIEW') "
            "AND table_schema NOT IN ('information_schema', 'pg_catalog', 'pg_toast') "
            f"AND table_name NOT IN ('{excluded}') "
            "ORDER BY table_schema, table_name"
        )
    )
    tables = rows.fetchall()

    sources: list[DataSource] = []
    for schema_name, table_name, table_type in tables:
        columns = await discover_columns(session, schema_name, table_name)
        schema_q = quote_ident(schema_name)
        table_q = quote_ident(table_name)
        count_result = await session.execute(text(f"SELECT COUNT(*) FROM {schema_q}.{table_q}"))
        row_count = count_result.scalar() or 0
        sources.append(
            DataSource(
                schema_name=schema_name,
                table_name=table_name,
                columns=columns,
                row_count=row_count,
                is_view=(table_type == "VIEW"),
            )
        )
    return sources

# =============================================================================
# SQL Audit — registro inmutable de ejecuciones del motor Text-to-SQL
# =============================================================================
# Registra question, generated_sql, tablas, tiempo, filas, costo y estado.
# NUNCA registra credenciales ni contenido de filas de datos de negocio.
# La tabla se crea idempotentemente en runtime (patrón rag_evaluations).
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_SQL_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS sql_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    user_id UUID,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    question TEXT NOT NULL,
    generated_sql TEXT,
    tables JSONB NOT NULL DEFAULT '[]',
    execution_time_ms DOUBLE PRECISION DEFAULT 0,
    rows INTEGER DEFAULT 0,
    cost DOUBLE PRECISION,
    status VARCHAR(30) NOT NULL,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_INDEX_ORG = (
    "CREATE INDEX IF NOT EXISTS idx_sql_audit_org "
    "ON sql_audit_logs(organization_id, created_at DESC)"
)
_INDEX_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_sql_audit_status "
    "ON sql_audit_logs(organization_id, status, created_at DESC)"
)


async def ensure_sql_audit_table() -> None:
    """Crea tabla e índices de auditoría SQL (idempotente)."""
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(text(_SQL_AUDIT_TABLE))
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning("Failed to ensure sql_audit_logs table")
    try:
        await session.execute(text(_INDEX_ORG))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(_INDEX_STATUS))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def write_sql_audit(
    *,
    organization_id: UUID,
    user_id: UUID | None,
    role: str,
    question: str,
    generated_sql: str,
    tables: list[str],
    execution_time_ms: float,
    rows: int,
    cost: float | None,
    status: str,
    error: str | None = None,
) -> None:
    """Escribe una entrada de auditoría. Fail-silent: nunca rompe el flujo."""
    try:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO sql_audit_logs "
                    "(organization_id, user_id, role, question, generated_sql, "
                    "tables, execution_time_ms, rows, cost, status, error) "
                    "VALUES (:oid, :uid, :role, :question, :sql, "
                    "CAST(:tables AS jsonb), :ms, :rows, :cost, :status, :error)"
                ),
                {
                    "oid": organization_id,
                    "uid": user_id,
                    "role": role,
                    "question": question[:2000],
                    "sql": generated_sql[:5000],
                    "tables": json.dumps(tables or []),
                    "ms": round(execution_time_ms, 2),
                    "rows": rows,
                    "cost": cost,
                    "status": status[:30],
                    "error": (error or "")[:1000],
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("SQL audit write failed", error=str(exc))
        finally:
            await session.close()
    except Exception:
        pass


async def list_sql_audit(
    organization_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> list[dict]:
    """Últimas entradas de auditoría SQL de una organization (admin)."""
    session: AsyncSession = await get_async_session()
    try:
        query = (
            "SELECT id, user_id, role, question, generated_sql, tables, "
            "execution_time_ms, rows, cost, status, error, created_at "
            "FROM sql_audit_logs WHERE organization_id = :oid "
        )
        params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
        if status:
            query += "AND status = :status "
            params["status"] = status
        query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        result = await session.execute(text(query), params)
        return [
            {
                "id": str(row.id),
                "user_id": str(row.user_id) if row.user_id else None,
                "role": row.role,
                "question": row.question,
                "generated_sql": row.generated_sql,
                "tables": row.tables if isinstance(row.tables, list) else [],
                "execution_time_ms": row.execution_time_ms,
                "rows": row.rows,
                "cost": row.cost,
                "status": row.status,
                "error": row.error,
                "created_at": row.created_at.isoformat(),
            }
            for row in result.fetchall()
        ]
    finally:
        await session.close()

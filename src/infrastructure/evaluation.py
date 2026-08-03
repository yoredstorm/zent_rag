# =============================================================================
# Evaluation Storage — Feedback collection and RAG quality metrics
# =============================================================================
# Stores thumbs up/down feedback with optional comments and computes
# aggregated quality scores per tenant/role.
# =============================================================================
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.logging_config import get_logger
from src.infrastructure.relational_db import get_async_session

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# SQL Migration (applied by `ensure_eval_table`)
# ---------------------------------------------------------------------------
_EVAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS rag_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    query_id UUID,
    conversation_id UUID,
    query TEXT NOT NULL,
    answer TEXT,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    rating VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
    comment TEXT,
    model VARCHAR(100),
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms DOUBLE PRECISION DEFAULT 0,
    method VARCHAR(10) DEFAULT 'rag',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_evals_tenant ON rag_evaluations(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rag_evals_role ON rag_evaluations(tenant_id, role, created_at DESC);
"""


async def ensure_eval_table() -> None:
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS rag_evaluations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                tenant_id UUID NOT NULL,
                query_id UUID,
                conversation_id UUID,
                query TEXT NOT NULL,
                answer TEXT,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                rating VARCHAR(10) NOT NULL CHECK (rating IN ('up', 'down')),
                comment TEXT,
                model VARCHAR(100),
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms DOUBLE PRECISION DEFAULT 0,
                method VARCHAR(10) DEFAULT 'rag',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_rag_evals_tenant "
            "ON rag_evaluations(tenant_id, created_at DESC)"
        ))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_rag_evals_role "
            "ON rag_evaluations(tenant_id, role, created_at DESC)"
        ))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def store_feedback(
    tenant_id: UUID,
    query: str,
    rating: str,
    query_id: UUID | None = None,
    conversation_id: UUID | None = None,
    answer: str = "",
    role: str = "admin",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: float = 0.0,
    method: str = "rag",
    comment: str = "",
) -> None:
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(
            text(
                "INSERT INTO rag_evaluations (tenant_id, query_id, conversation_id, "
                "query, answer, role, rating, comment, model, "
                "prompt_tokens, completion_tokens, total_tokens, latency_ms, method) "
                "VALUES (:tenant_id, :query_id, :conversation_id, "
                ":query, :answer, :role, :rating, :comment, :model, "
                ":prompt_tokens, :completion_tokens, :total_tokens, :latency_ms, :method)"
            ),
            {
                "tenant_id": tenant_id,
                "query_id": query_id,
                "conversation_id": conversation_id,
                "query": query,
                "answer": answer,
                "role": role,
                "rating": rating,
                "comment": comment,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
                "method": method,
            },
        )
        await session.commit()
        logger.info("Feedback stored", tenant_id=str(tenant_id), rating=rating)
    except Exception as exc:
        await session.rollback()
        logger.error("Failed to store feedback", error=str(exc))
    finally:
        await session.close()


async def get_stats(
    tenant_id: UUID,
    role: str | None = None,
    days: int = 30,
) -> dict:
    session: AsyncSession = await get_async_session()
    try:
        role_filter = "AND role = :role" if role else ""
        params: dict[str, str | int] = {
            "tenant_id": str(tenant_id),
            "days": str(days),
        }
        if role:
            params["role"] = role

        result = await session.execute(
            text(
                "SELECT "
                "  COUNT(*) FILTER (WHERE rating = 'up') AS thumbs_up, "
                "  COUNT(*) FILTER (WHERE rating = 'down') AS thumbs_down, "
                "  COUNT(*) AS total, "
                "  ROUND(AVG(latency_ms)) AS avg_latency_ms, "
                "  ROUND(AVG(total_tokens)) AS avg_tokens, "
                "  COUNT(DISTINCT model) AS models_used "
                "FROM rag_evaluations "
                "WHERE tenant_id = CAST(:tenant_id AS uuid) "
                "  AND created_at >= NOW() - (:days || ' days')::interval "
                + role_filter
            ),
            params,
        )
        row = result.fetchone()
        total = row.total or 0
        thumbs_up = row.thumbs_up or 0
        return {
            "tenant_id": str(tenant_id),
            "role": role or "all",
            "period_days": days,
            "total_evaluations": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": row.thumbs_down or 0,
            "approval_rate": round(thumbs_up / total * 100, 1) if total > 0 else 0.0,
            "avg_latency_ms": round(row.avg_latency_ms, 1) if row.avg_latency_ms else 0,
            "avg_tokens": round(row.avg_tokens) if row.avg_tokens else 0,
            "models_used": row.models_used or 0,
        }
    finally:
        await session.close()


async def get_recent(
    tenant_id: UUID,
    limit: int = 20,
) -> list[dict]:
    session: AsyncSession = await get_async_session()
    try:
        result = await session.execute(
            text(
                "SELECT id, query_id, query, answer, role, rating, comment, "
                "model, total_tokens, latency_ms, method, created_at "
                "FROM rag_evaluations "
                "WHERE tenant_id = :tenant_id "
                "ORDER BY created_at DESC "
                "LIMIT :limit"
            ),
            {"tenant_id": tenant_id, "limit": limit},
        )
        return [
            {
                "id": str(row.id),
                "query_id": str(row.query_id) if row.query_id else None,
                "query": row.query[:200],
                "answer": row.answer[:300] if row.answer else "",
                "role": row.role,
                "rating": row.rating,
                "comment": row.comment,
                "model": row.model,
                "total_tokens": row.total_tokens,
                "latency_ms": row.latency_ms,
                "method": row.method,
                "created_at": row.created_at.isoformat(),
            }
            for row in result.fetchall()
        ]
    finally:
        await session.close()

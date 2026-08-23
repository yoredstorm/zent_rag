# =============================================================================
# Agent Trace Store — persistencia de execution traces (agent_runs)
# =============================================================================
# Guarda run completo: pasos, tool calls, latencias, tokens, costo.
# NUNCA secrets ni argumentos completos (todo truncado por el runtime).
# =============================================================================
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_AGENT_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    agent_id UUID NOT NULL,
    user_id UUID,
    role VARCHAR(20) NOT NULL DEFAULT 'admin',
    status VARCHAR(30) NOT NULL,
    message TEXT NOT NULL,
    answer TEXT,
    steps JSONB NOT NULL DEFAULT '[]',
    total_latency_ms DOUBLE PRECISION DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    cost DOUBLE PRECISION DEFAULT 0,
    injection_detected BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

_INDEX_ORG = (
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_org "
    "ON agent_runs(organization_id, created_at DESC)"
)
_INDEX_AGENT = (
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_agent "
    "ON agent_runs(agent_id, created_at DESC)"
)


async def ensure_agent_runs_table() -> None:
    session: AsyncSession = await get_async_session()
    try:
        await session.execute(text(_AGENT_RUNS_TABLE))
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning("Failed to ensure agent_runs table")
    try:
        await session.execute(text(_INDEX_ORG))
        await session.commit()
    except Exception:
        await session.rollback()
    try:
        await session.execute(text(_INDEX_AGENT))
        await session.commit()
    except Exception:
        await session.rollback()
    finally:
        await session.close()


async def save_run(result) -> None:
    """Persiste un AgentRunResult (fail-silent)."""
    try:
        session: AsyncSession = await get_async_session()
        try:
            await session.execute(
                text(
                    "INSERT INTO agent_runs "
                    "(id, organization_id, agent_id, user_id, role, status, "
                    "message, answer, steps, total_latency_ms, total_tokens, "
                    "cost, injection_detected) "
                    "VALUES (:id, :oid, :aid, :uid, :role, :status, :message, "
                    ":answer, CAST(:steps AS jsonb), :latency, :tokens, "
                    ":cost, :injection)"
                ),
                {
                    "id": result.run_id,
                    "oid": result.organization_id,
                    "aid": result.agent_id,
                    "uid": result.user_id,
                    "role": result.role,
                    "status": result.status,
                    "message": (result.message or "")[:2000],
                    "answer": (result.answer or "")[:8000],
                    "steps": json.dumps(result.steps or []),
                    "latency": round(result.total_latency_ms, 2),
                    "tokens": result.total_tokens,
                    "cost": round(result.cost, 6),
                    "injection": result.injection_detected,
                },
            )
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning("Agent run save failed", error=str(exc))
        finally:
            await session.close()
    except Exception:
        pass


async def get_run(organization_id: UUID, run_id: UUID) -> dict | None:
    session: AsyncSession = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, organization_id, agent_id, user_id, role, "
                    "status, message, answer, steps, total_latency_ms, "
                    "total_tokens, cost, injection_detected, created_at "
                    "FROM agent_runs "
                    "WHERE organization_id = :oid AND id = :rid"
                ),
                {"oid": organization_id, "rid": run_id},
            )
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row.id),
            "agent_id": str(row.agent_id),
            "user_id": str(row.user_id) if row.user_id else None,
            "role": row.role,
            "status": row.status,
            "message": row.message,
            "answer": row.answer,
            "steps": row.steps if isinstance(row.steps, list) else [],
            "total_latency_ms": row.total_latency_ms,
            "total_tokens": row.total_tokens,
            "cost": row.cost,
            "injection_detected": row.injection_detected,
            "created_at": row.created_at.isoformat(),
        }
    finally:
        await session.close()


async def list_runs(
    organization_id: UUID,
    agent_id: UUID | None = None,
    *,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    session: AsyncSession = await get_async_session()
    try:
        query = (
            "SELECT id, agent_id, user_id, role, status, message, "
            "total_latency_ms, total_tokens, cost, injection_detected, "
            "created_at FROM agent_runs WHERE organization_id = :oid "
        )
        params: dict = {"oid": organization_id, "limit": limit, "offset": offset}
        if agent_id is not None:
            query += "AND agent_id = :aid "
            params["aid"] = agent_id
        query += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        rows = (await session.execute(text(query), params)).fetchall()
        return [
            {
                "id": str(r.id),
                "agent_id": str(r.agent_id),
                "user_id": str(r.user_id) if r.user_id else None,
                "role": r.role,
                "status": r.status,
                "message": r.message[:300],
                "total_latency_ms": r.total_latency_ms,
                "total_tokens": r.total_tokens,
                "cost": r.cost,
                "injection_detected": r.injection_detected,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        await session.close()

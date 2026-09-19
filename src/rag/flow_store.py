"""Flujo por respuesta RAG — traza completa para el chat (Ver flujo).

Una fila por query. El writer es best-effort: un fallo de persistencia nunca
rompe la respuesta.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)


async def record_flow(
    *,
    query_id: UUID,
    organization_id: UUID,
    flow: dict,
    conversation_id: UUID | None = None,
    request_id: UUID | None = None,
    user_id: UUID | None = None,
    method: str = "rag",
    status: str = "completed",
) -> None:
    """Persiste el flujo. Nunca lanza: se registra el warning y sigue."""
    session = await get_async_session()
    try:
        await session.execute(
            text(
                """
                INSERT INTO rag_flows (
                    query_id, organization_id, conversation_id, request_id,
                    user_id, method, status, flow
                ) VALUES (
                    :query_id, :organization_id, :conversation_id, :request_id,
                    :user_id, :method, :status, CAST(:flow AS jsonb)
                )
                ON CONFLICT (query_id) DO UPDATE SET
                    method = EXCLUDED.method,
                    status = EXCLUDED.status,
                    flow = EXCLUDED.flow
                """
            ),
            {
                "query_id": query_id,
                "organization_id": organization_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
                "user_id": user_id,
                "method": (method or "rag")[:20],
                "status": (status or "completed")[:30],
                "flow": json.dumps(flow, default=str),
            },
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.warning("rag flow persist failed", error=str(exc)[:200])
    finally:
        await session.close()


async def get_flow(organization_id: UUID, query_id: UUID) -> dict | None:
    """Flujo de una query, scoped por organización. None si no existe."""
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    """
                    SELECT flow, method, status, created_at
                    FROM rag_flows
                    WHERE organization_id = :oid AND query_id = :qid
                    """
                ),
                {"oid": organization_id, "qid": query_id},
            )
        ).mappings().first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rag flow read failed", error=str(exc)[:200])
        return None
    finally:
        await session.close()
    if row is None:
        return None
    flow = dict(row["flow"] or {})
    flow.setdefault("method", row["method"])
    flow.setdefault("status", row["status"])
    created = row["created_at"]
    if created is not None and hasattr(created, "isoformat"):
        flow.setdefault("created_at", created.isoformat())
    return flow

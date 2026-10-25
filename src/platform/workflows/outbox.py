# =============================================================================
# Transactional outbox — el evento de negocio y su registro se persisten en la
# misma transacción. Redis/NATS es transporte, no almacén autoritativo.
# =============================================================================
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.postgres.session import get_async_session

logger = get_logger(__name__)

_OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS workflow_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    workspace_id UUID,
    aggregate_type VARCHAR(60) NOT NULL,
    aggregate_key VARCHAR(200) NOT NULL,
    event_id UUID NOT NULL,
    event_type VARCHAR(120) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    available_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ,
    attempts INT NOT NULL DEFAULT 0,
    last_error VARCHAR(400),
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, event_id)
)
"""

_ENSURED = False


async def ensure_outbox_table() -> None:
    global _ENSURED
    if _ENSURED:
        return
    session = await get_async_session()
    try:
        await session.execute(text(_OUTBOX_DDL))
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_wf_outbox_dispatch "
                "ON workflow_outbox(available_at, created_at) WHERE delivered_at IS NULL"
            )
        )
        await session.commit()
        _ENSURED = True
    except Exception as exc:  # noqa: BLE001 — paridad dev; migración manda
        await session.rollback()
        logger.warning("ensure_outbox_table failed", error=str(exc)[:200])
    finally:
        await session.close()


async def enqueue(
    session,
    *,
    organization_id: UUID,
    workspace_id: UUID | None,
    aggregate_type: str,
    aggregate_key: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    event_id: UUID | None = None,
    available_at: datetime | None = None,
) -> UUID:
    """Inserta el evento en la transacción del productor."""
    eid = event_id or uuid4()
    body = dict(payload or {})
    body.setdefault("event_id", str(eid))
    await session.execute(
        text(
            "INSERT INTO workflow_outbox "
            "(organization_id, workspace_id, aggregate_type, aggregate_key, event_id, "
            "event_type, payload, headers, available_at) "
            "VALUES (:oid, :ws, :atype, :akey, :eid, :etype, CAST(:payload AS jsonb), "
            "CAST(:headers AS jsonb), :available) "
            "ON CONFLICT (organization_id, event_id) DO NOTHING"
        ),
        {
            "oid": organization_id,
            "ws": workspace_id,
            "atype": aggregate_type[:60],
            "akey": aggregate_key[:200],
            "eid": eid,
            "etype": event_type[:120],
            "payload": json.dumps(body, default=str),
            "headers": json.dumps(headers or {}, default=str),
            "available": available_at or datetime.now(timezone.utc),
        },
    )
    return eid


async def dispatch_pending(*, limit: int = 50) -> dict[str, int]:
    """Publica eventos pendientes. Si el bus falla, quedan en la tabla."""
    await ensure_outbox_table()
    session = await get_async_session()
    try:
        rows = (
            await session.execute(
                text(
                    "SELECT * FROM workflow_outbox "
                    "WHERE delivered_at IS NULL "
                    "AND (lease_expires_at IS NULL OR lease_expires_at < NOW()) "
                    "AND available_at <= NOW() "
                    "ORDER BY created_at LIMIT :lim FOR UPDATE SKIP LOCKED"
                ),
                {"lim": max(1, min(int(limit), 200))},
            )
        ).fetchall()
        if rows:
            await session.execute(
                text(
                    "UPDATE workflow_outbox SET lease_expires_at = NOW() + make_interval(mins => 5) "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": [row.id for row in rows]},
            )
        await session.commit()
    finally:
        await session.close()

    delivered = failed = 0
    for row in rows:
        try:
            from src.platform.realtime.stream import publish_event

            payload = dict(row.payload or {})
            payload["event_id"] = str(row.event_id)
            payload.setdefault("organization_id", str(row.organization_id))
            if row.workspace_id:
                payload.setdefault("workspace_id", str(row.workspace_id))
            payload.setdefault("dedupe_key", f"outbox:{row.event_id}")
            await publish_event(str(row.event_type), payload)
            session = await get_async_session()
            try:
                await session.execute(
                    text(
                        "UPDATE workflow_outbox SET delivered_at = NOW(), "
                        "lease_expires_at = NULL, attempts = attempts + 1, last_error = NULL "
                        "WHERE id = :id"
                    ),
                    {"id": row.id},
                )
                await session.commit()
            finally:
                await session.close()
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            session = await get_async_session()
            try:
                backoff = min(3600, 2 ** min(int(row.attempts or 0) + 1, 10))
                await session.execute(
                    text(
                        "UPDATE workflow_outbox SET attempts = attempts + 1, "
                        "last_error = :error, lease_expires_at = NULL, "
                        "available_at = NOW() + make_interval(secs => CAST(:backoff AS DOUBLE PRECISION)) "
                        "WHERE id = :id"
                    ),
                    {"error": str(exc)[:400], "backoff": backoff, "id": row.id},
                )
                await session.commit()
            finally:
                await session.close()
            logger.warning(
                "workflow outbox dispatch failed",
                event_id=str(row.event_id),
                error=str(exc)[:200],
            )
    return {"claimed": len(rows), "delivered": delivered, "failed": failed}


async def backlog() -> dict[str, int]:
    await ensure_outbox_table()
    session = await get_async_session()
    try:
        row = (
            await session.execute(
                text(
                    "SELECT COUNT(*) AS pending, "
                    "COUNT(*) FILTER (WHERE available_at <= NOW()) AS ready, "
                    "MIN(created_at) AS oldest FROM workflow_outbox "
                    "WHERE delivered_at IS NULL"
                )
            )
        ).fetchone()
    finally:
        await session.close()
    oldest = row.oldest if row and row.oldest else None
    age = int((datetime.now(timezone.utc) - oldest).total_seconds()) if oldest else 0
    return {
        "pending": int(row.pending or 0) if row else 0,
        "ready": int(row.ready or 0) if row else 0,
        "oldest_age_seconds": age,
    }


__all__ = ["backlog", "dispatch_pending", "enqueue", "ensure_outbox_table"]

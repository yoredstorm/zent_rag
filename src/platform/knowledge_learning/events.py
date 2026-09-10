# =============================================================================
# Knowledge Learning Events — durable + realtime (FASE 33)
# =============================================================================
# Los eventos se persisten en knowledge_events (replay y auditoría) y se
# publican en el canal Redis `rag:events` para SSE cuando el flag
# RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED está activo.
#
# Toda animación/estado de la UI debe proceder de estos eventos reales.
# =============================================================================
from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from src.core.config import get_settings
from src.core.domain.knowledge_learning import event_category
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

logger = get_logger(__name__)

_HEARTBEAT_SECONDS = 15
_EVENT_PREFIX = "knowledge."
_SUBSCRIBE_TIMEOUT = 2.0


class KnowledgeEventEmitter:
    """Emite eventos reales: persistencia durable + publicación realtime."""

    def __init__(self, repository: Any) -> None:
        self._repo = repository

    async def emit(
        self,
        *,
        organization_id: UUID,
        event_type: str,
        message: str = "",
        run_id: UUID | None = None,
        source_id: UUID | None = None,
        stage: str | None = None,
        severity: str = "info",
        payload: dict | None = None,
    ) -> dict:
        event = await self._repo.append_event(
            organization_id,
            event_type=event_type,
            run_id=run_id,
            source_id=source_id,
            stage=stage,
            category=event_category(event_type).value,
            severity=severity,
            message=message,
            payload=payload,
        )
        if get_settings().RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED:
            await self._publish(event)
        return event

    async def _publish(self, event: dict) -> None:
        try:
            from src.platform.realtime.stream import (
                EVENTS_CHANNEL,
                publish_event,
            )

            await publish_event(
                event["event_type"],
                {
                    "organization_id": event["organization_id"],
                    "run_id": event["run_id"],
                    "source_id": event["source_id"],
                    "stage": event["stage"],
                    "category": event["category"],
                    "severity": event["severity"],
                    "message": event["message"],
                    "payload": event["payload"],
                    "seq": event["seq"],
                    "created_at": event["created_at"],
                    "channel": EVENTS_CHANNEL,  # trazabilidad del bus
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Knowledge event publish failed", error=str(exc)[:200])


async def knowledge_event_source(
    organization_id: UUID,
    *,
    run_id: UUID | None = None,
    since_seq: int = 0,
    replay_limit: int = 200,
    repository: Any | None = None,
):
    """Generador SSE: replay durable desde knowledge_events + live por Redis.

    El replay garantiza que un cliente que llega tarde reciba el progreso real
    ya ocurrido; luego se suscribe al bus para eventos nuevos. Heartbeat cada
    15s (mismo contrato que /api/v1/platform/realtime/stream).
    """
    repo = repository
    if repo is None:
        from src.platform.knowledge_learning.repository import (
            PostgresKnowledgeLearningRepository,
        )

        repo = PostgresKnowledgeLearningRepository()

    org = str(organization_id)
    last_seq = max(0, int(since_seq))
    try:
        history = await repo.list_events(
            organization_id,
            run_id=run_id,
            since_seq=last_seq,
            limit=replay_limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Knowledge event replay failed", error=str(exc)[:200])
        history = []

    for event in history:
        last_seq = max(last_seq, int(event.get("seq") or 0))
        yield _format_sse(event)

    client = await _get_redis()
    pubsub = client.pubsub()
    from src.platform.realtime.stream import EVENTS_CHANNEL

    await pubsub.subscribe(EVENTS_CHANNEL)
    try:
        it = pubsub.listen().__aiter__()
        while True:
            try:
                message = await asyncio.wait_for(
                    it.__anext__(), timeout=_HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                yield "event: heartbeat\ndata: {}\n\n"
                continue
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, json.JSONDecodeError):
                continue
            if payload.get("organization_id") != org:
                continue
            if not str(payload.get("event", "")).startswith(_EVENT_PREFIX):
                continue
            if run_id is not None and payload.get("run_id") != str(run_id):
                continue
            seq = int(payload.get("seq") or 0)
            if seq and seq <= last_seq:
                continue
            last_seq = max(last_seq, seq)
            yield _format_sse(payload)
    finally:
        try:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
        except Exception:  # noqa: BLE001
            pass


def _format_sse(payload: dict) -> str:
    event_type = payload.get("event") or payload.get("event_type") or "event"
    return f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"

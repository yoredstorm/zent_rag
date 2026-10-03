# =============================================================================
# Learning Session Emitter — eventos semánticos reales, agregados y durables
# =============================================================================
# Contrato:
#   - Cada evento nace de trabajo realmente ocurrido (compiler / pipeline).
#   - Alta frecuencia: se agregan en ventanas de 250 ms. 50 ENTITY_DISCOVERED
#     se convierten en UN evento con payload.count=50 y hasta 4 muestras.
#   - Cada evento se persiste (replay) y se publica en el bus Redis `rag:events`
#     con prefijo `knowledge.session.` para SSE.
#   - Los eventos crudos se conservan internamente (ring buffer acotado) para
#     inspección técnica; a la UI va la versión agregada.
# =============================================================================
from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.core.domain.knowledge_session import (
    HIGH_FREQUENCY_EVENTS,
    SessionEventType,
)
from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.redis.cache import _get_redis

from .semantics import describe, severity_for

logger = get_logger(__name__)

FLUSH_INTERVAL_SECONDS = 0.25
MAX_SAMPLES_PER_EVENT = 4
MAX_RAW_EVENTS = 2000
EVENT_PREFIX = "knowledge.session."
_HEARTBEAT_SECONDS = 15

# Métrica del Pulse que incrementa cada tipo de evento.
_EVENT_METRICS: dict[str, str] = {
    SessionEventType.SEMANTIC_UNIT_CREATED.value: "semantic_units",
    SessionEventType.SEMANTIC_RECONSTRUCTED.value: "reconstruction_sources",
    SessionEventType.CONTINUATIONS_MERGED.value: "merged_continuations",
    SessionEventType.FRAGMENTS_REJECTED.value: "fragments_rejected",
    SessionEventType.SCHEMAS_INFERRED.value: "schemas_inferred",
    SessionEventType.ENTITY_DISCOVERED.value: "entities_new",
    SessionEventType.ENTITY_MATCHED.value: "entities_enriched",
    SessionEventType.ENTITY_MERGED.value: "merges",
    SessionEventType.FACT_DISCOVERED.value: "facts_new",
    SessionEventType.FACT_REINFORCED.value: "facts_reinforced",
    SessionEventType.RELATIONSHIP_DISCOVERED.value: "relationships",
    SessionEventType.RULE_DISCOVERED.value: "rules",
    SessionEventType.EVIDENCE_LINKED.value: "evidence",
    SessionEventType.CONFLICT_DETECTED.value: "conflicts",
    SessionEventType.DUPLICATE_DETECTED.value: "duplicates",
    SessionEventType.TABLE_DETECTED.value: "tables",
}

# Métricas compuestas del Pulse: lo que la UI muestra como contador principal.
PULSE_ALIASES: dict[str, tuple[str, ...]] = {
    "entities": ("entities_new", "entities_enriched"),
    "facts": ("facts_new", "facts_reinforced"),
}


class LearningSessionObserver:
    """Observa el aprendizaje real de una fuente dentro de una sesión."""

    def __init__(
        self,
        repository: Any,
        *,
        session_id: UUID,
        organization_id: UUID,
        source_row_id: UUID | None = None,
        source_id: UUID | None = None,
        name: str = "",
        source_type: str = "file",
    ) -> None:
        self._repo = repository
        self.session_id = session_id
        self.organization_id = organization_id
        self.source_row_id = source_row_id
        self.source_id = source_id
        self.name = name
        self.source_type = source_type

        self.stage: str | None = None
        self.counters: dict[str, int] = {}
        self.raw_events: deque[dict] = deque(maxlen=MAX_RAW_EVENTS)
        self._pending: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._closed = False

    # ---------------------------------------------------------------- métricas
    async def metric(self, key: str, value: int = 1) -> None:
        """Contador crudo (no siempre tiene evento asociado)."""
        if not key:
            return
        self.counters[key] = int(self.counters.get(key, 0)) + int(value)

    def metrics_snapshot(self) -> dict:
        snapshot = dict(self.counters)
        for alias, keys in PULSE_ALIASES.items():
            snapshot[alias] = sum(int(snapshot.get(key, 0)) for key in keys)
        if self.source_id:
            snapshot["sources"] = 1
        return snapshot

    # ------------------------------------------------------------------ stage
    async def set_stage(self, stage: str) -> None:
        if stage == self.stage:
            return
        self.stage = stage
        await self._touch_source()

    # ----------------------------------------------------------------- eventos
    async def event(
        self,
        event_type: str,
        *,
        payload: dict | None = None,
        message: str | None = None,
        severity: str | None = None,
        count: int = 1,
    ) -> None:
        count = max(1, int(count))
        metric_key = _EVENT_METRICS.get(event_type)
        if metric_key:
            await self.metric(metric_key, count)

        raw = {
            "event_type": event_type,
            "payload": dict(payload or {}),
            "at": datetime.now(timezone.utc).isoformat(),
        }
        self.raw_events.append(raw)

        if event_type in HIGH_FREQUENCY_EVENTS:
            entry = self._pending.get(event_type)
            if entry is None:
                entry = {
                    "event_type": event_type,
                    "count": 0,
                    "samples": [],
                    "message": message or describe(event_type, payload),
                    "severity": severity or severity_for(event_type, payload),
                    "stage": self.stage,
                }
                self._pending[event_type] = entry
            entry["count"] += count
            entry["stage"] = self.stage
            sample = dict(payload or {})
            if sample and len(entry["samples"]) < MAX_SAMPLES_PER_EVENT:
                entry["samples"].append(sample)
            # El texto se recalcula con el conteo agregado real de la ventana.
            entry["message"] = message or describe(
                event_type, {**sample, "count": entry["count"]}
            )
            self._ensure_flusher()
            return

        # Evento significativo: vaciar pendientes y escribirlo de inmediato.
        await self._flush()
        await self._write_events(
            [
                {
                    "event_type": event_type,
                    "count": count,
                    "samples": [dict(payload or {})] if payload else [],
                    "message": message or describe(event_type, payload),
                    "severity": severity or severity_for(event_type, payload),
                    "stage": self.stage,
                }
            ]
        )

    async def warning(self, message: str, *, payload: dict | None = None) -> None:
        await self.event(
            SessionEventType.WARNING.value,
            message=message,
            payload=payload,
            severity="warning",
        )

    # -------------------------------------------------------------- ciclo vida
    async def source_received(self) -> None:
        await self.metric("sources", 1)
        await self.event(
            SessionEventType.SOURCE_RECEIVED.value,
            payload={"name": self.name, "source_type": self.source_type},
        )

    async def source_available(self, *, stats: dict | None = None) -> None:
        if stats:
            for key, value in stats.items():
                await self.metric(str(key), int(value))
        await self.event(
            SessionEventType.SOURCE_AVAILABLE.value,
            payload={"name": self.name, **self.counters},
        )

    async def source_completed(self) -> None:
        await self.event(
            SessionEventType.KNOWLEDGE_READY.value,
            payload=dict(self.counters),
        )

    async def source_failed(self, human_message: str, *, technical: str = "") -> None:
        await self.event(
            SessionEventType.SOURCE_FAILED.value,
            message=human_message,
            payload={"name": self.name, "technical": technical[:500]},
            severity="error",
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session final flush failed", error=str(exc)[:200])
        task = self._flush_task
        self._flush_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ interno
    def _ensure_flusher(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._flush_task = loop.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
                await self._flush()
                if self._closed and not self._pending:
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session flush loop stopped", error=str(exc)[:200])

    async def _flush(self) -> None:
        async with self._lock:
            if not self._pending:
                return
            pending = list(self._pending.values())
            self._pending.clear()
        await self._write_events(pending)

    async def _write_events(self, pending: list[dict]) -> None:
        if not pending:
            return
        events: list[dict] = []
        for entry in pending:
            payload: dict[str, Any] = {"count": entry["count"]}
            if entry["samples"]:
                payload["items"] = entry["samples"]
                payload.update(
                    {key: value for key, value in entry["samples"][0].items() if key not in payload}
                )
            events.append(
                {
                    "session_id": self.session_id,
                    "source_id": self.source_id,
                    "event_type": entry["event_type"],
                    "stage": entry["stage"],
                    "severity": entry["severity"],
                    "message": entry["message"],
                    "payload": payload,
                    "aggregate": entry["count"] > 1,
                }
            )
        try:
            rows = await self._repo.append_events(
                self.organization_id, events=events
            )
        except Exception as exc:  # noqa: BLE001 — la ingesta nunca se frena
            logger.warning(
                "Learning session events persist failed",
                session_id=str(self.session_id),
                error=str(exc)[:200],
            )
            return
        for row in rows:
            await self._publish(row)
        await self._touch_source()
        try:
            await self._repo.refresh_session_rollup(
                self.organization_id, self.session_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Learning session rollup failed", error=str(exc)[:200])

    async def _touch_source(self) -> None:
        if self.source_row_id is None:
            return
        try:
            await self._repo.update_source(
                self.source_row_id,
                stats=self.metrics_snapshot(),
                **({"stage": self.stage} if self.stage else {}),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Learning session source touch failed", error=str(exc)[:160])

    async def _publish(self, event: dict) -> None:
        try:
            from src.core.config import get_settings

            if not get_settings().RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED:
                return
            from src.platform.realtime.stream import publish_event

            await publish_event(
                EVENT_PREFIX + str(event.get("event_type", "")).lower(),
                {
                    "session_id": event.get("session_id"),
                    "organization_id": event.get("organization_id"),
                    "source_id": event.get("source_id"),
                    "event_type": event.get("event_type"),
                    "stage": event.get("stage"),
                    "severity": event.get("severity"),
                    "message": event.get("message"),
                    "payload": event.get("payload"),
                    "aggregate": event.get("aggregate"),
                    "seq": event.get("seq"),
                    "created_at": event.get("created_at"),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Learning session publish failed", error=str(exc)[:160])

    # ---------------------------------------------------------------- inspección
    def technical_snapshot(self) -> dict:
        return {
            "session_id": str(self.session_id),
            "source_id": str(self.source_id) if self.source_id else None,
            "name": self.name,
            "stage": self.stage,
            "metrics": self.metrics_snapshot(),
            "raw_events": list(self.raw_events),
            "pending": [
                {"event_type": key, "count": value["count"]}
                for key, value in self._pending.items()
            ],
        }


# ---------------------------------------------------------------------------
# SSE: replay durable + live por el bus existente
# ---------------------------------------------------------------------------


def _format_sse(payload: dict) -> str:
    event_type = payload.get("event_type") or payload.get("event") or "event"
    return f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"


async def learning_session_event_source(
    organization_id: UUID,
    session_id: UUID,
    *,
    since_seq: int = 0,
    replay_limit: int = 400,
    repository: Any | None = None,
):
    """Generador SSE de una Knowledge Session.

    Replay durable (nada se pierde si el cliente llega tarde) + live por
    ``rag:events``. Heartbeat cada 15 s. El filtro es por session_id, así que
    nunca se cuela actividad de otra sesión.
    """
    repo = repository
    if repo is None:
        from .repository import PostgresKnowledgeSessionRepository

        repo = PostgresKnowledgeSessionRepository()

    org = str(organization_id)
    sid = str(session_id)
    last_seq = max(0, int(since_seq))
    try:
        history = await repo.list_events(
            organization_id, session_id, since_seq=last_seq, limit=replay_limit
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Learning session replay failed", error=str(exc)[:200])
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
            if payload.get("session_id") != sid:
                continue
            event = str(payload.get("event", ""))
            if not event.startswith(EVENT_PREFIX):
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


__all__ = [
    "EVENT_PREFIX",
    "FLUSH_INTERVAL_SECONDS",
    "LearningSessionObserver",
    "PULSE_ALIASES",
    "learning_session_event_source",
]

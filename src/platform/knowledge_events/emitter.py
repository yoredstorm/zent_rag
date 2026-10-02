# =============================================================================
# KnowledgeSystemEventEmitter — dominio → bus durable (C8, W5).
# =============================================================================
# El inner (`KnowledgeEventEmitter`) persiste y decide la publicación realtime
# según RAG_KNOWLEDGE_LIVE_EVENTS_ENABLED; este adaptador no duplica el gate.
# Fail-soft: cualquier excepción se registra como warning y nunca propaga.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.core.domain.knowledge_events import KnowledgeSystemEvent
from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)

_CATEGORY = "knowledge"


class KnowledgeSystemEventEmitter:
    """Adapta eventos de dominio C8 al emitter durable existente."""

    def __init__(self, inner: object) -> None:
        self._inner: Any = inner

    async def emit(self, event: KnowledgeSystemEvent) -> None:
        """Delega en el bus real; cualquier fallo se registra y se descarta."""
        try:
            await self._inner.emit(
                organization_id=event.organization_id,
                event_type=event.event_name,
                message=event.event_name,
                source_id=event.source_id,
                severity="warning" if event.requires_review else "info",
                payload={
                    **(event.payload or {}),
                    **event.to_public_dict(),
                    "category": _CATEGORY,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Knowledge system event emit failed",
                event_type=event.event_name,
                error=str(exc)[:200],
            )

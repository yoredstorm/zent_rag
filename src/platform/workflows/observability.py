# =============================================================================
# Living Workflows observability — métricas y logs estructurados (misión §35).
# Mismo patrón fail-soft que runtime.py: si prometheus no está, no rompe nada.
# =============================================================================
from __future__ import annotations

from typing import Any

from src.infrastructure.observability.logging_config import get_logger

logger = get_logger(__name__)


def _counter(name: str, description: str, labels: tuple[str, ...] = ()):
    try:
        from prometheus_client import Counter

        return Counter(name, description, list(labels))
    except Exception:  # noqa: BLE001
        return None


def _histogram(name: str, description: str, labels: tuple[str, ...] = ()):
    try:
        from prometheus_client import Histogram

        return Histogram(name, description, list(labels))
    except Exception:  # noqa: BLE001
        return None


workflow_events_received_total = _counter(
    "workflow_events_received_total", "Eventos recibidos por el dispatcher", ("source",)
)
workflow_events_processed_total = _counter(
    "workflow_events_processed_total", "Eventos procesados sin error", ("event_type",)
)
workflow_events_failed_total = _counter(
    "workflow_events_failed_total", "Eventos que fallaron al procesar", ("event_type",)
)
workflow_event_deduplicated_total = _counter(
    "workflow_event_deduplicated_total", "Eventos descartados por dedupe"
)
workflow_watcher_checks_total = _counter(
    "workflow_watcher_checks_total", "Checks de watchers", ("outcome",)
)
workflow_watcher_transitions_total = _counter(
    "workflow_watcher_transitions_total", "Transiciones detectadas por watchers"
)
workflow_triggers_fired_total = _counter(
    "workflow_triggers_fired_total", "Workflows disparados por eventos/watchers"
)
workflow_trigger_latency_seconds = _histogram(
    "workflow_trigger_latency_seconds", "Latencia entre received_at y dispatch", ("source",)
)
workflow_auto_paused_total = _counter(
    "workflow_auto_paused_total", "Workflows pausados automáticamente por fallos"
)


def log_event(  # noqa: PLR0913
    *,
    organization_id: Any,
    workflow_id: Any | None = None,
    event_type: str | None = None,
    correlation_id: str | None = None,
    watcher_id: Any | None = None,
    outcome: str | None = None,
    error: str | None = None,
) -> None:
    """Log estructurado con organización, workflow, evento y correlación."""
    logger.info(
        "workflow event",
        organization_id=str(organization_id) if organization_id else None,
        workflow_id=str(workflow_id) if workflow_id else None,
        event_type=event_type,
        correlation_id=correlation_id,
        watcher_id=str(watcher_id) if watcher_id else None,
        outcome=outcome,
        error=error[:300] if error else None,
    )


__all__ = [
    "log_event",
    "workflow_auto_paused_total",
    "workflow_event_deduplicated_total",
    "workflow_events_failed_total",
    "workflow_events_processed_total",
    "workflow_events_received_total",
    "workflow_trigger_latency_seconds",
    "workflow_triggers_fired_total",
    "workflow_watcher_checks_total",
    "workflow_watcher_transitions_total",
]

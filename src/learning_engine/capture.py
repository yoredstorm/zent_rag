# =============================================================================
# Captura barata desde un decision trace. El análisis no corre aquí.
# =============================================================================
from __future__ import annotations

from src.core.domain.learning_cycle import RunSignal
from src.infrastructure.observability.logging_config import get_logger
from src.learning_engine.schedule import enabled

logger = get_logger(__name__)


async def capture_decision_trace(trace) -> None:
    if not enabled() or trace.organization_id is None:
        return
    capability = (trace.selected_capability or "decision")[:80]
    try:
        from src.learning_engine.wiring import learning_engine

        await learning_engine().note(
            RunSignal(
                organization_id=trace.organization_id,
                pattern_key=capability or "decision",
                intent_family=(capability or "decision")[:80],
                route_label=capability,
                jev_capability=(trace.jev_capability or "")[:80],
                executed_capability=((trace.actual_capability or trace.selected_capability) or "")[:80],
                fallback=bool(trace.fallback_used),
                success=trace.agreement,
                cost=float(trace.estimated_cost or 0.0),
                latency_ms=float(trace.latency_ms or 0.0),
                source_type="decision",
            )
        )
    except Exception as exc:  # noqa: BLE001 — la traza ya se guardó
        logger.warning("learning cycle capture failed", error=str(exc)[:200])

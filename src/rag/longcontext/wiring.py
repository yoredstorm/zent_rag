# =============================================================================
# Wiring del Long-Context Engine — settings + factory + métricas
# =============================================================================
from __future__ import annotations

from collections.abc import Callable

from src.infrastructure.observability.logging_config import get_logger
from src.infrastructure.observability.metrics import (
    zent_long_context_expansions,
    zent_long_context_tokens,
    zent_long_context_total,
)
from src.rag.longcontext.engine import AdaptiveLongContextEngine
from src.rag.longcontext.expansion import ExpansionStrategy, RetrieveFn
from src.rag.longcontext.packager import ContextPackager
from src.rag.longcontext.settings import LongContextSettings, settings_from_app

logger = get_logger(__name__)


def long_context_settings() -> LongContextSettings:
    return settings_from_app()


def engine_from_settings(
    *,
    retrieve_fn: RetrieveFn,
    settings: LongContextSettings | None = None,
    store: object | None = None,
    strategies: list[ExpansionStrategy] | None = None,
    packager: ContextPackager | None = None,
    evidence_check: Callable | None = None,
) -> AdaptiveLongContextEngine | None:
    """Construye el engine o None si el modo es off (comportamiento actual)."""
    resolved = settings or settings_from_app()
    if not resolved.enabled():
        return None
    return AdaptiveLongContextEngine(
        retrieve_fn=retrieve_fn,
        settings=resolved,
        store=store,
        strategies=strategies,
        packager=packager,
        evidence_check=evidence_check,
    )


def observe_long_context(mode: str, result) -> None:
    """Métrica best-effort: nunca rompe la respuesta."""
    try:
        zent_long_context_total.labels(
            mode=mode, stop_reason=result.stop_reason
        ).inc()
        zent_long_context_tokens.observe(result.final_tokens)
        zent_long_context_expansions.observe(len(result.expansions))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Long-context metrics failed", error=str(exc)[:150])


__all__ = [
    "engine_from_settings",
    "long_context_settings",
    "observe_long_context",
]

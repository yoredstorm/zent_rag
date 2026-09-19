# =============================================================================
# Decision Engine process-wide accessor.
# =============================================================================
# The API layer (composition root) configures the factory with the LLM
# provider. Lower layers (agents, workflows) import this module instead of
# src.api.deps, so the dependency direction stays api -> agents -> decision.
# =============================================================================
from __future__ import annotations

from typing import Callable

_engine = None
_factory: Callable[[], object] | None = None


def configure_decision_engine(factory: Callable[[], object]) -> None:
    """Register the composition-root factory. Call once at startup."""
    global _factory
    _factory = factory


def set_decision_engine(engine: object) -> None:
    global _engine
    _engine = engine


def get_decision_engine():
    """Lazy singleton. Falls back to the plain factory without an LLM."""
    global _engine
    if _engine is None:
        if _factory is not None:
            _engine = _factory()
        else:
            from src.decision.factory import build_decision_engine

            _engine = build_decision_engine()
    return _engine

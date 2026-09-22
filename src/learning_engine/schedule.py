# =============================================================================
# Job periódico. No hace polling agresivo: mínimo 5 minutos.
# =============================================================================
from __future__ import annotations

import os
from datetime import timedelta

from src.learning_engine.engine import LearningEngine


def enabled() -> bool:
    return os.getenv("LEARNING_CYCLE_ENABLED", "").strip().lower() in {"1", "true", "yes"}


def interval_seconds() -> int:
    raw = os.getenv("LEARNING_CYCLE_INTERVAL_SECONDS", "900")
    try:
        value = int(raw)
    except ValueError:
        value = 900
    return max(300, value)


async def run_periodic(engine: LearningEngine) -> int:
    return await engine.analyze_recent(limit=50)


def cutoff_delta() -> timedelta:
    return timedelta(seconds=interval_seconds())

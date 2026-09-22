# =============================================================================
# Composition root. Postgres en runtime. Tests construyen el doble.
# =============================================================================
from __future__ import annotations

import os

from src.learning_engine.engine import LearningEngine


def learning_engine() -> LearningEngine:
    from src.infrastructure.postgres.learning_cycle_store import PostgresLearningCycleStore
    from src.memory.wiring import memory_foundation_service

    every_n = _int("LEARNING_CYCLE_EVERY_N", 50)
    min_sample = _int("LEARNING_CYCLE_MIN_SAMPLE", 20)
    return LearningEngine(
        PostgresLearningCycleStore(),
        memory_foundation_service(),
        every_n=max(1, every_n),
        min_sample=max(1, min_sample),
    )


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)

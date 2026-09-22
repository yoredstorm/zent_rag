# =============================================================================
# Ventanas temporales. Una sola ejecución no dispara un hallazgo.
# =============================================================================
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.domain.learning_cycle import RunSignal, WindowName


def window_start(window: WindowName | str, now: datetime | None = None) -> datetime | None:
    name = WindowName(window)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if name == WindowName.ALL_TIME:
        return None
    span = {
        WindowName.LAST_HOUR: timedelta(hours=1),
        WindowName.LAST_24H: timedelta(hours=24),
        WindowName.LAST_7D: timedelta(days=7),
        WindowName.LAST_30D: timedelta(days=30),
    }[name]
    return current - span


def slice_window(
    signals: list[RunSignal],
    window: WindowName | str,
    now: datetime | None = None,
) -> list[RunSignal]:
    start = window_start(window, now)
    if start is None:
        return list(signals)
    selected: list[RunSignal] = []
    for signal in signals:
        occurred = signal.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        if occurred >= start:
            selected.append(signal)
    return selected


def confidence_for(sample_size: int) -> str:
    if sample_size < 20:
        return "low"
    if sample_size < 50:
        return "medium"
    return "high"

# =============================================================================
# Rate limiter asíncrono — el excedente espera, no rompe.
# =============================================================================
from __future__ import annotations

import time

import pytest

from src.infrastructure.resilience.rate_limiter import AsyncRateLimiter


@pytest.mark.asyncio
async def test_disabled_limiter_passes_through() -> None:
    limiter = AsyncRateLimiter(0)
    start = time.monotonic()
    for _ in range(50):
        await limiter.acquire()
    assert time.monotonic() - start < 0.2


@pytest.mark.asyncio
async def test_excess_waits_for_the_window() -> None:
    limiter = AsyncRateLimiter(2, window_seconds=0.5)
    start = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()  # excedente: espera a que venza la ventana
    elapsed = time.monotonic() - start
    assert elapsed >= 0.35

# =============================================================================
# Rate limiter asíncrono (token bucket por ventana) para el proveedor LLM.
# =============================================================================
# El proveedor aplica su propio límite por API key (p. ej. 30 req/min): si el
# runtime lo supera, responde 429 y el pipeline degrada. Este limitador hace
# esperar los pedidos excedentes en vez de romperlos. 0 = deshabilitado.
# =============================================================================
from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncRateLimiter:
    """Máximo `rate_per_minute` adquisiciones por ventana de 60s."""

    def __init__(self, rate_per_minute: int, window_seconds: float = 60.0) -> None:
        self._rate = max(0, int(rate_per_minute))
        self._window = max(1.0, float(window_seconds))
        self._events: deque[float] = deque()
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._rate > 0

    async def acquire(self) -> None:
        if not self.enabled:
            return
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._events and now - self._events[0] >= self._window:
                    self._events.popleft()
                if len(self._events) < self._rate:
                    self._events.append(now)
                    return
                wait = self._window - (now - self._events[0])
            await asyncio.sleep(max(0.01, wait))

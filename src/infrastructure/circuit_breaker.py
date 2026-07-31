# =============================================================================
# Circuit Breaker — In-memory fail-fast for LLM / Embedding calls
# =============================================================================
# Tracks consecutive failures per operation type. After the threshold is
# reached, the circuit opens for 30 s and all calls fail instantly without
# touching the external API. After the timeout, a single half-open probe is
# allowed; if it succeeds the circuit closes, otherwise it re-opens.
# =============================================================================
from __future__ import annotations

import enum
import time
from typing import Any, Awaitable, Callable

from src.infrastructure.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CircuitBreakerOpenError(Exception):
    """Raised when the circuit is open and the call is rejected immediately."""
    pass


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class _CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout

        # Per-operation state
        self._states: dict[str, _CircuitState] = {}
        self._failure_counts: dict[str, int] = {}
        self._open_since: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_state(self, name: str) -> _CircuitState:
        return self._states.get(name, _CircuitState.CLOSED)

    def _set_state(self, name: str, new_state: _CircuitState) -> None:
        old_state = self._states.get(name)
        self._states[name] = new_state
        if old_state != new_state:
            logger.warning(
                "Circuit breaker state transition",
                operation=name,
                old_state=old_state.value if old_state else "unknown",
                new_state=new_state.value,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def call(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        state = self._get_state(name)

        # --- Open: check if recovery timeout has elapsed ---------------
        if state == _CircuitState.OPEN:
            elapsed = time.monotonic() - self._open_since.get(name, 0)
            if elapsed >= self._recovery_timeout:
                self._set_state(name, _CircuitState.HALF_OPEN)
                logger.info(
                    "Circuit breaker entering half-open state", operation=name
                )
            else:
                remaining = self._recovery_timeout - elapsed
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN for '{name}'. "
                    f"Retry in {remaining:.1f}s."
                )

        # --- Attempt the call ------------------------------------------
        try:
            result = await func(*args, **kwargs)
        except Exception:
            self._on_failure(name)
            raise

        self._on_success(name)
        return result

    # ------------------------------------------------------------------
    # Internal state transitions
    # ------------------------------------------------------------------

    def _on_failure(self, name: str) -> None:
        self._failure_counts[name] = self._failure_counts.get(name, 0) + 1
        state = self._get_state(name)

        if (
            state == _CircuitState.CLOSED
            and self._failure_counts[name] >= self._failure_threshold
        ):
            self._set_state(name, _CircuitState.OPEN)
            self._open_since[name] = time.monotonic()
            logger.warning(
                "Circuit breaker opened",
                operation=name,
                failures=self._failure_counts[name],
            )

        elif state == _CircuitState.HALF_OPEN:
            self._set_state(name, _CircuitState.OPEN)
            self._open_since[name] = time.monotonic()
            logger.warning(
                "Circuit breaker re-opened after half-open probe failed",
                operation=name,
                failures=self._failure_counts[name],
            )

    def _on_success(self, name: str) -> None:
        self._failure_counts[name] = 0
        if self._get_state(name) == _CircuitState.HALF_OPEN:
            self._set_state(name, _CircuitState.CLOSED)
            logger.info(
                "Circuit breaker closed after successful half-open probe",
                operation=name,
            )

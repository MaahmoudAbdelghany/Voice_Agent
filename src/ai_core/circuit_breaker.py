"""
Circuit Breaker Pattern for AI Model Gateway.

Protects against cascading timeouts, rate limit storms, and slow provider failures
by maintaining per-provider state: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from enum import Enum

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    """States of a Circuit Breaker."""

    CLOSED = "CLOSED"  # Normal operation: requests pass through
    OPEN = "OPEN"  # Provider down: requests fail fast without network call
    HALF_OPEN = "HALF_OPEN"  # Testing recovery: exactly one probe request permitted


class CircuitBreaker:
    """
    In-memory async Circuit Breaker with sliding-window consecutive failure tracking,
    configurable cooldown, and single-probe HALF_OPEN recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        window_s: float = 60.0,
        cooldown_s: float = 60.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        """
        Initialize Circuit Breaker.

        Args:
            name: Human-readable identifier for provider/service (e.g. 'groq', 'gemini').
            failure_threshold: Consecutive retryable failures before tripping to OPEN.
            window_s: Rolling window in seconds within which failures count.
            cooldown_s: Time in seconds to stay OPEN before allowing a HALF_OPEN probe.
            time_fn: Optional clock source for test determinism (defaults to time.monotonic).
        """
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.window_s = max(1.0, window_s)
        self.cooldown_s = max(1.0, cooldown_s)
        self._time_fn = time_fn or time.monotonic

        self._state: BreakerState = BreakerState.CLOSED
        self._consecutive_failures: int = 0
        self._failure_timestamps: list[float] = []
        self._opened_at: float | None = None
        self._probe_in_flight: bool = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BreakerState:
        """Current state of the breaker (thread-safe inspection)."""
        return self._state

    @property
    def consecutive_failures(self) -> int:
        """Number of consecutive retryable failures."""
        return self._consecutive_failures

    @property
    def opened_at(self) -> float | None:
        """Timestamp when breaker entered OPEN state, if applicable."""
        return self._opened_at

    async def allow_request(self) -> bool:
        """
        Determine if a request should be permitted to reach the provider.

        Returns:
            True if request is allowed (CLOSED or successful probe in HALF_OPEN).
            False if request must be skipped fast (OPEN or concurrent in HALF_OPEN).
        """
        async with self._lock:
            now = self._time_fn()

            if self._state == BreakerState.CLOSED:
                return True

            if self._state == BreakerState.OPEN:
                assert self._opened_at is not None
                elapsed = now - self._opened_at
                if elapsed >= self.cooldown_s:
                    logger.info(
                        "Circuit breaker [%s] cooldown expired (%.2fs >= %.2fs). Entering HALF_OPEN.",
                        self.name,
                        elapsed,
                        self.cooldown_s,
                    )
                    self._state = BreakerState.HALF_OPEN
                    self._probe_in_flight = True
                    return True
                return False

            if self._state == BreakerState.HALF_OPEN:
                # Exactly one probe allowed concurrently
                if not self._probe_in_flight:
                    self._probe_in_flight = True
                    return True
                return False

        return False

    async def record_success(self) -> None:
        """Record a successful request completion."""
        async with self._lock:
            if self._state == BreakerState.HALF_OPEN:
                logger.info(
                    "Circuit breaker [%s] probe succeeded. Recovering state to CLOSED.",
                    self.name,
                )
            self._state = BreakerState.CLOSED
            self._consecutive_failures = 0
            self._failure_timestamps.clear()
            self._opened_at = None
            self._probe_in_flight = False

    async def record_failure(self, is_retryable: bool = True) -> None:
        """
        Record a request failure.

        Args:
            is_retryable: Whether this failure counts toward breaker health
                          (timeouts, 429, 5xx, connection errors). Non-retryable
                          errors (400, 401, 404) are ignored by the breaker.
        """
        if not is_retryable:
            return

        async with self._lock:
            now = self._time_fn()

            if self._state == BreakerState.HALF_OPEN:
                logger.warning(
                    "Circuit breaker [%s] probe failed. Tripping back to OPEN.",
                    self.name,
                )
                self._state = BreakerState.OPEN
                self._opened_at = now
                self._probe_in_flight = False
                return

            if self._state == BreakerState.CLOSED:
                # Prune timestamps outside rolling window
                cutoff = now - self.window_s
                self._failure_timestamps = [t for t in self._failure_timestamps if t >= cutoff]

                # If all previous failures expired outside window, reset consecutive count
                if not self._failure_timestamps:
                    self._consecutive_failures = 0

                self._failure_timestamps.append(now)
                self._consecutive_failures += 1

                if self._consecutive_failures >= self.failure_threshold:
                    self._state = BreakerState.OPEN
                    self._opened_at = now
                    logger.error(
                        "Circuit breaker [%s] tripped OPEN after %d consecutive failures within %.1fs window.",
                        self.name,
                        self._consecutive_failures,
                        self.window_s,
                    )

    def snapshot(self) -> dict[str, object]:
        """Return point-in-time snapshot of circuit breaker metrics."""
        now = self._time_fn()
        opened_for = (now - self._opened_at) if self._opened_at else 0.0
        remaining_cooldown = (
            max(0.0, self.cooldown_s - opened_for) if self._state == BreakerState.OPEN else 0.0
        )

        return {
            "name": self.name,
            "state": self._state.value,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "window_s": self.window_s,
            "cooldown_s": self.cooldown_s,
            "opened_at": self._opened_at,
            "remaining_cooldown_s": round(remaining_cooldown, 2),
            "probe_in_flight": self._probe_in_flight,
        }

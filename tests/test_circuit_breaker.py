"""
Unit tests for Circuit Breaker logic (Feature 4.1 / Tier 1).
"""

import asyncio

import pytest

from src.ai_core.circuit_breaker import BreakerState, CircuitBreaker


class FakeClock:
    """Controllable clock for deterministic circuit breaker timing tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self._current_time = start

    def __call__(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> None:
        self._current_time += seconds


@pytest.mark.asyncio
async def test_starts_closed_and_allows():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=3, time_fn=clock)

    assert cb.state == BreakerState.CLOSED
    assert cb.consecutive_failures == 0
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_trips_after_threshold_consecutive_failures():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=3, window_s=60.0, time_fn=clock)

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.CLOSED
    assert cb.consecutive_failures == 2
    assert await cb.allow_request() is True

    # 3rd failure trips the breaker
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN
    assert cb.consecutive_failures == 3
    assert await cb.allow_request() is False


@pytest.mark.asyncio
async def test_success_resets_counter():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=3, time_fn=clock)

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.consecutive_failures == 2

    # A success resets the consecutive failure counter
    await cb.record_success()
    assert cb.consecutive_failures == 0
    assert cb.state == BreakerState.CLOSED

    # Next two failures don't trip it
    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.CLOSED
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_failures_outside_window_restart_count():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=3, window_s=60.0, time_fn=clock)

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.consecutive_failures == 2

    # Advance clock past window
    clock.advance(65.0)

    # Next failure should notice older ones expired
    await cb.record_failure(is_retryable=True)
    assert cb.consecutive_failures == 1
    assert cb.state == BreakerState.CLOSED
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_half_open_after_cooldown_single_probe():
    clock = FakeClock()
    cb = CircuitBreaker(
        "test-provider",
        failure_threshold=2,
        cooldown_s=30.0,
        time_fn=clock,
    )

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN
    assert await cb.allow_request() is False

    # Still inside cooldown window
    clock.advance(15.0)
    assert await cb.allow_request() is False

    # Pass cooldown: first request transitions to HALF_OPEN and is allowed
    clock.advance(16.0)
    assert await cb.allow_request() is True
    assert cb.state == BreakerState.HALF_OPEN

    # Concurrent request while probe is in flight is rejected
    assert await cb.allow_request() is False


@pytest.mark.asyncio
async def test_probe_success_closes():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=2, cooldown_s=30.0, time_fn=clock)

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN

    clock.advance(35.0)
    assert await cb.allow_request() is True
    assert cb.state == BreakerState.HALF_OPEN

    # Successful probe closes breaker
    await cb.record_success()
    assert cb.state == BreakerState.CLOSED
    assert cb.consecutive_failures == 0
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_probe_failure_reopens_with_new_cooldown():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=2, cooldown_s=30.0, time_fn=clock)

    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN

    clock.advance(35.0)
    assert await cb.allow_request() is True
    assert cb.state == BreakerState.HALF_OPEN

    # Probe fails: immediately trips back to OPEN with new timestamp
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN
    assert await cb.allow_request() is False

    # Must wait another full 30s cooldown
    clock.advance(20.0)
    assert await cb.allow_request() is False
    clock.advance(11.0)
    assert await cb.allow_request() is True
    assert cb.state == BreakerState.HALF_OPEN


@pytest.mark.asyncio
async def test_non_retryable_does_not_trip():
    clock = FakeClock()
    cb = CircuitBreaker("test-provider", failure_threshold=2, time_fn=clock)

    await cb.record_failure(is_retryable=False)
    await cb.record_failure(is_retryable=False)
    await cb.record_failure(is_retryable=False)

    assert cb.state == BreakerState.CLOSED
    assert cb.consecutive_failures == 0
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_snapshot_fields():
    clock = FakeClock(start=500.0)
    cb = CircuitBreaker(
        "groq-test",
        failure_threshold=3,
        window_s=45.0,
        cooldown_s=30.0,
        time_fn=clock,
    )

    snap = cb.snapshot()
    assert snap["name"] == "groq-test"
    assert snap["state"] == "CLOSED"
    assert snap["consecutive_failures"] == 0
    assert snap["failure_threshold"] == 3
    assert snap["window_s"] == 45.0
    assert snap["cooldown_s"] == 30.0
    assert snap["remaining_cooldown_s"] == 0.0

    # Trip breaker
    for _ in range(3):
        await cb.record_failure(is_retryable=True)

    clock.advance(10.0)
    snap_open = cb.snapshot()
    assert snap_open["state"] == "OPEN"
    assert snap_open["consecutive_failures"] == 3
    assert snap_open["remaining_cooldown_s"] == 20.0


@pytest.mark.asyncio
async def test_concurrent_allow_requests():
    clock = FakeClock()
    cb = CircuitBreaker("concurrent-test", failure_threshold=2, cooldown_s=10.0, time_fn=clock)

    # Trip breaker
    await cb.record_failure(is_retryable=True)
    await cb.record_failure(is_retryable=True)
    assert cb.state == BreakerState.OPEN

    # Advance clock to enter HALF_OPEN on next call
    clock.advance(15.0)

    # 10 concurrent requests attempting to probe
    results = await asyncio.gather(*[cb.allow_request() for _ in range(10)])

    # Exactly ONE request should be allowed as probe!
    assert results.count(True) == 1
    assert results.count(False) == 9

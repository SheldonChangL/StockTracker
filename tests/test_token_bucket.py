"""Tests for the shared token-bucket rate limiter (Story 3.1, AC-2/AC-3)."""

from __future__ import annotations

import threading
import time

import pytest

from tsic.ratelimit.token_bucket import TokenBucket


class FakeClock:
    """Deterministic monotonic clock whose ``sleep`` advances virtual time."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_acquire_spaces_grants_by_at_least_one_second() -> None:
    # AC-2: TokenBucket(rate=1/s) with an injected fake clock; three consecutive
    # acquire() calls must obtain tokens at least 1 second apart.
    clock = FakeClock()
    bucket = TokenBucket(rate=1.0, time_fn=clock.time, sleep_fn=clock.sleep)

    grants: list[float] = []
    for _ in range(3):
        bucket.acquire()
        grants.append(clock.now)

    intervals = [b - a for a, b in zip(grants, grants[1:])]
    assert all(gap >= 1.0 for gap in intervals)


def test_acquire_returns_seconds_waited() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate=1.0, time_fn=clock.time, sleep_fn=clock.sleep)

    assert bucket.acquire() == 0.0  # first token served from the initial fill
    assert bucket.acquire() == pytest.approx(1.0)  # next must wait one interval


def test_acquire_more_than_capacity_is_rejected() -> None:
    bucket = TokenBucket(rate=1.0, capacity=1.0)
    with pytest.raises(ValueError):
        bucket.acquire(2)


@pytest.mark.parametrize("bad_rate", [0, -1.0])
def test_non_positive_rate_is_rejected(bad_rate: float) -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate=bad_rate)


def test_concurrent_acquire_respects_rate_limit() -> None:
    # AC-3: many threads sharing one bucket must not race past the rate ceiling.
    # With capacity tokens granted up front, n grants require at least
    # (n - capacity) / rate seconds of enforced spacing; a race would finish
    # sooner. Real clock; we assert only the guaranteed lower bound (never flaky
    # on the slow side, since sleeps can only lengthen the run).
    rate = 50.0
    interval = 1.0 / rate
    capacity = 1.0
    n_threads = 8
    bucket = TokenBucket(rate=rate, capacity=capacity)

    grants: list[float] = []
    grants_lock = threading.Lock()
    start_barrier = threading.Barrier(n_threads)

    def worker() -> None:
        start_barrier.wait()
        bucket.acquire()
        with grants_lock:
            grants.append(time.monotonic())

    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.monotonic() - start

    assert len(grants) == n_threads
    assert elapsed >= (n_threads - capacity) * interval

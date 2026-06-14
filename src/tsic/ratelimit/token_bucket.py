"""Thread-safe token-bucket rate limiter (Story 3.1, ADR-4; NFR-7).

A :class:`TokenBucket` enforces an upstream request-rate ceiling so a data
source is never hammered hard enough to get the client's IP throttled or
banned (e.g. TWSE's ``<= 1 req/s`` budget). Tokens refill continuously at
``rate`` tokens per second, up to ``capacity`` tokens of burst; each
:meth:`acquire` consumes tokens, blocking until enough have accrued.

The clock is injectable (``time_fn`` / ``sleep_fn``) so timing behaviour can be
driven deterministically by a fake clock in tests instead of real wall-clock
sleeps. The whole of :meth:`acquire` runs under a single lock, so a bucket may
be shared by many threads (one per concurrent fetch task) without races — this
is what lets every task of one source share *one* bucket (ADR-2).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class TokenBucket:
    """A continuously refilling, thread-safe token bucket.

    Args:
        rate: Token refill rate in tokens per second. Must be positive. For a
            ``<= 1 req/s`` source pass ``rate=1``.
        capacity: Maximum tokens that can accumulate (burst size). Defaults to
            ``1``, i.e. a strict no-burst limiter that grants at most one token
            ahead of schedule. Must be positive.
        time_fn: Monotonic time source returning seconds. Injectable for tests;
            defaults to :func:`time.monotonic`.
        sleep_fn: Blocking sleep taking a seconds argument. Injectable for
            tests; defaults to :func:`time.sleep`.
    """

    def __init__(
        self,
        rate: float,
        capacity: float = 1.0,
        *,
        time_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], object] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")

        self._rate = float(rate)
        self._capacity = float(capacity)
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._lock = threading.Lock()

        # Start full so the first acquire is served immediately, then the rate
        # ceiling governs every subsequent acquire.
        self._available = self._capacity
        self._last = time_fn()

    @property
    def rate(self) -> float:
        """Refill rate in tokens per second."""
        return self._rate

    @property
    def capacity(self) -> float:
        """Maximum tokens that can accumulate (burst size)."""
        return self._capacity

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until ``tokens`` are available, consume them, and return waited.

        The entire critical section (refill, check, and any sleep) is held under
        one lock, so concurrent callers are serialized and the rate ceiling
        holds regardless of how many threads share this bucket.

        Args:
            tokens: Number of tokens to consume (default ``1``).

        Returns:
            The total seconds spent sleeping while waiting for tokens (``0.0``
            when the request was served immediately) — useful for observability.

        Raises:
            ValueError: If ``tokens`` exceeds the bucket capacity (such a
                request could never be satisfied).
        """
        if tokens > self._capacity:
            raise ValueError(
                f"cannot acquire {tokens} tokens from a bucket of "
                f"capacity {self._capacity}"
            )

        waited = 0.0
        with self._lock:
            while True:
                now = self._time_fn()
                elapsed = now - self._last
                self._last = now
                self._available = min(
                    self._capacity, self._available + elapsed * self._rate
                )

                if self._available >= tokens:
                    self._available -= tokens
                    return waited

                deficit = tokens - self._available
                wait = deficit / self._rate
                self._sleep_fn(wait)
                waited += wait

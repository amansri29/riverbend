"""In-process circuit breaker (ADR-10). Per worker instance, which is a known limitation
noted in docs/not-built.md: at scale the breaker state belongs in a shared store."""

from __future__ import annotations

import time
from collections.abc import Callable


class CircuitBreaker:
    """In-process breaker: opens after N consecutive failures, half-opens after a cool-down."""

    def __init__(self, *, failure_threshold: int, open_seconds: float, clock: Callable[[], float] = time.monotonic):
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def failures(self) -> int:
        """Consecutive failures seen since the last success (for logs)."""
        return self._failures

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = self._clock()

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at < self.open_seconds:
            return True
        # Half-open: let one call through; a failure re-opens immediately.
        self._opened_at = None
        self._failures = self.failure_threshold - 1
        return False

    def retry_after_seconds(self) -> float:
        if self._opened_at is None:
            return 0.0
        return max(0.0, self.open_seconds - (self._clock() - self._opened_at))

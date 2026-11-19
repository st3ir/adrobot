"""In-process sliding-window rate limiting.

Good enough for a single-process deployment, which is what this tool targets.
With several workers, swap this class for a Redis-backed implementation; the
interface is intentionally tiny.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol


class RateLimiter(Protocol):
    """What the middleware needs from a limiter."""

    def allow(self, key: str) -> bool: ...
    def retry_after(self, key: str) -> int: ...


class SlidingWindowRateLimiter:
    """Allows at most ``max_events`` per ``window_seconds`` per key."""

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self._max_events = max_events
        self._window = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record an attempt; return ``False`` when the key is over budget."""
        now = time.monotonic()
        bucket = self._events[key]
        self._evict(bucket, now)
        if len(bucket) >= self._max_events:
            return False
        bucket.append(now)
        return True

    def retry_after(self, key: str) -> int:
        bucket = self._events.get(key)
        if not bucket:
            return 0
        return max(1, int(self._window - (time.monotonic() - bucket[0])) + 1)

    def reset(self, key: str) -> None:
        self._events.pop(key, None)

    def _evict(self, bucket: deque[float], now: float) -> None:
        threshold = now - self._window
        while bucket and bucket[0] <= threshold:
            bucket.popleft()

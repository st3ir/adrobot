"""A tiny async TTL cache for Keitaro reference data."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class TTLCache[T]:
    """Caches a single value for ``ttl_seconds`` and de-duplicates refreshes.

    Keitaro's reference lists (offers, domains, groups, sources) change rarely
    but are requested on every page load; caching them keeps the UI snappy and
    protects the tracker from avoidable load.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._value: T | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, loader: Callable[[], Awaitable[T]]) -> T:
        now = time.monotonic()
        if self._value is not None and now < self._expires_at:
            return self._value
        async with self._lock:
            # Another coroutine may have refreshed while we waited.
            now = time.monotonic()
            if self._value is not None and now < self._expires_at:
                return self._value
            value = await loader()
            self._value = value
            self._expires_at = time.monotonic() + self._ttl
            return value

    def invalidate(self) -> None:
        self._value = None
        self._expires_at = 0.0

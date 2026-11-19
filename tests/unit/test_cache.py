"""TTL cache behaviour."""

from __future__ import annotations

import asyncio

from app.services.cache import TTLCache


class TestTTLCache:
    async def test_caches_within_the_ttl(self) -> None:
        calls = 0

        async def load() -> int:
            nonlocal calls
            calls += 1
            return calls

        cache: TTLCache[int] = TTLCache(60)
        assert await cache.get(load) == 1
        assert await cache.get(load) == 1
        assert calls == 1

    async def test_reloads_after_expiry(self) -> None:
        calls = 0

        async def load() -> int:
            nonlocal calls
            calls += 1
            return calls

        cache: TTLCache[int] = TTLCache(0.05)
        await cache.get(load)
        await asyncio.sleep(0.08)
        await cache.get(load)
        assert calls == 2

    async def test_concurrent_misses_load_once(self) -> None:
        calls = 0

        async def load() -> int:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return calls

        cache: TTLCache[int] = TTLCache(60)
        await asyncio.gather(*(cache.get(load) for _ in range(10)))
        assert calls == 1

    async def test_invalidate_forces_a_reload(self) -> None:
        calls = 0

        async def load() -> int:
            nonlocal calls
            calls += 1
            return calls

        cache: TTLCache[int] = TTLCache(60)
        await cache.get(load)
        cache.invalidate()
        await cache.get(load)
        assert calls == 2

"""Sliding-window rate limiter."""

from __future__ import annotations

import time

from app.core.rate_limit import SlidingWindowRateLimiter


class TestSlidingWindowRateLimiter:
    def test_allows_up_to_the_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(3, window_seconds=60)
        assert [limiter.allow("ip") for _ in range(4)] == [True, True, True, False]

    def test_keys_are_independent(self) -> None:
        limiter = SlidingWindowRateLimiter(1, window_seconds=60)
        assert limiter.allow("a")
        assert limiter.allow("b")
        assert not limiter.allow("a")

    def test_window_expires(self) -> None:
        limiter = SlidingWindowRateLimiter(1, window_seconds=0.2)
        assert limiter.allow("ip")
        assert not limiter.allow("ip")
        time.sleep(0.25)
        assert limiter.allow("ip")

    def test_reset_clears_a_key(self) -> None:
        limiter = SlidingWindowRateLimiter(1, window_seconds=60)
        limiter.allow("ip")
        limiter.reset("ip")
        assert limiter.allow("ip")

    def test_retry_after_is_positive_when_blocked(self) -> None:
        limiter = SlidingWindowRateLimiter(1, window_seconds=30)
        limiter.allow("ip")
        assert limiter.retry_after("ip") > 0
        assert limiter.retry_after("unknown") == 0

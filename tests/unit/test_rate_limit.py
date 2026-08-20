"""Unit tests for the in-memory rate limiter."""

from __future__ import annotations

from app.core.config import RateLimitRule
from app.core.rate_limit import RateLimiter

RULE = RateLimitRule(limit=3, window_seconds=60)


class TestRateLimiter:
    def test_allows_up_to_limit(self) -> None:
        limiter = RateLimiter()
        assert all(limiter.check("b", "ip1", RULE) for _ in range(3))

    def test_blocks_over_limit(self) -> None:
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("b", "ip1", RULE)
        assert not limiter.check("b", "ip1", RULE)

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("b", "ip1", RULE)
        assert limiter.check("b", "ip2", RULE)

    def test_buckets_are_independent(self) -> None:
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("bucket-a", "ip1", RULE)
        assert limiter.check("bucket-b", "ip1", RULE)

    def test_window_expires(self) -> None:
        limiter = RateLimiter()
        for i in range(3):
            limiter.check("b", "ip1", RULE, now=float(i))
        # Still inside the window: blocked.
        assert not limiter.check("b", "ip1", RULE, now=30.0)
        # Window has expired: allowed again.
        assert limiter.check("b", "ip1", RULE, now=61.0)
        for _ in range(2):
            limiter.check("b", "ip1", RULE, now=61.5)
        # New window full again.
        assert not limiter.check("b", "ip1", RULE, now=62.0)

    def test_reset(self) -> None:
        limiter = RateLimiter()
        for _ in range(3):
            limiter.check("b", "ip1", RULE)
        limiter.reset()
        assert limiter.check("b", "ip1", RULE)

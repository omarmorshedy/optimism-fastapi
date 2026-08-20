"""Defensive per-IP rate limiting (decision #12, ADR-011).

In-memory fixed-window counters, suitable for the single-instance v1 deployment
(TD-05). Swap for a Redis-backed limiter when scaling horizontally.
"""

from __future__ import annotations

import threading
import time

from app.core.config import RateLimitRule
from app.core.metrics import RATE_LIMIT_EXCEEDED


class RateLimiter:
    """Thread-safe fixed-window rate limiter keyed by (bucket, client key)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # bucket -> {key: (window_start_ts, count)}
        self._windows: dict[str, dict[str, tuple[float, int]]] = {}

    def check(
        self, bucket: str, key: str, rule: RateLimitRule, *, now: float | None = None
    ) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic() if now is None else now
        with self._lock:
            windows = self._windows.setdefault(bucket, {})
            window_start, count = windows.get(key, (now, 0))
            if now - window_start >= rule.window_seconds:
                window_start, count = now, 0
            count += 1
            if count > rule.limit:
                RATE_LIMIT_EXCEEDED.labels(endpoint=bucket).inc()
                return False
            windows[key] = (window_start, count)
            return True

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()

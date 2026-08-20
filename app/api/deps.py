"""Shared API dependencies: rate limiting (per IP) and client-IP extraction."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from fastapi import Depends, Request

from app.core.config import RateLimitRule, Settings
from app.core.exceptions import rate_limited
from app.core.rate_limit import RateLimiter


def get_client_ip(request: Request) -> str:
    """Client IP for rate limiting; honours X-Forwarded-For (first hop)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def get_rate_limiter(request: Request) -> RateLimiter:
    return cast(RateLimiter, request.app.state.rate_limiter)


def rate_limit_dependency(
    bucket: str, rule_getter: Callable[[Settings], RateLimitRule]
) -> Callable[..., Any]:
    """Build a FastAPI dependency enforcing a per-IP rate limit (API_SPEC §1.5)."""

    def dependency(
        request: Request,
        limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
    ) -> None:
        settings: Settings = request.app.state.settings
        rule = rule_getter(settings)
        if not limiter.check(bucket, get_client_ip(request), rule):
            raise rate_limited(instance=str(request.url.path))

    return dependency


limit_booking_create = rate_limit_dependency("booking.create", lambda s: s.booking_create_limit)
limit_booking_cancel = rate_limit_dependency("booking.cancel", lambda s: s.booking_cancel_limit)
limit_calendar_read = rate_limit_dependency("calendar.read", lambda s: s.calendar_read_limit)
limit_admin_login = rate_limit_dependency("admin.login", lambda s: s.admin_login_limit)

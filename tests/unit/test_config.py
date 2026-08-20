"""Unit tests for Settings and rate-limit parsing."""

from __future__ import annotations

import pytest
from app.core.config import RateLimitRule, Settings, parse_rate_limit
from pydantic import ValidationError


class TestRateLimitParsing:
    def test_minute(self) -> None:
        assert parse_rate_limit("10/minute") == RateLimitRule(10, 60)

    def test_second(self) -> None:
        assert parse_rate_limit("60/second") == RateLimitRule(60, 1)

    def test_hour(self) -> None:
        assert parse_rate_limit("5/hour") == RateLimitRule(5, 3600)

    def test_bare_number_defaults_to_minute_window(self) -> None:
        assert parse_rate_limit("10") == RateLimitRule(10, 60)

    def test_unknown_unit_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_rate_limit("10/fortnight")

    def test_zero_limit_clamped_to_one(self) -> None:
        assert parse_rate_limit("0/minute").limit == 1


class TestSettings:
    def test_defaults(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.booking_cancellation_cutoff_minutes == 5
        assert settings.email_retry_max_attempts == 5
        assert settings.email_retry_base_delay_seconds == 60
        assert settings.email_retry_max_delay_seconds == 960
        assert settings.booking_create_limit == RateLimitRule(10, 60)
        assert settings.calendar_read_limit == RateLimitRule(60, 60)
        assert settings.booking_cancel_limit == RateLimitRule(10, 60)
        assert settings.admin_login_limit == RateLimitRule(5, 60)

    def test_env_overrides(self, monkeypatch) -> None:
        monkeypatch.setenv("BOOKING_CANCELLATION_CUTOFF_MINUTES", "30")
        monkeypatch.setenv("RATE_LIMIT_BOOKING_CREATE", "50/minute")
        settings = Settings(_env_file=None)
        assert settings.booking_cancellation_cutoff_minutes == 30
        assert settings.booking_create_limit == RateLimitRule(50, 60)

    def test_invalid_cutoff_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(booking_cancellation_cutoff_minutes=-1, _env_file=None)

    def test_invalid_retry_attempts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(email_retry_max_attempts=0, _env_file=None)

    def test_frozen(self) -> None:
        settings = Settings(_env_file=None)
        with pytest.raises(ValidationError):
            settings.log_level = "DEBUG"  # type: ignore[misc]

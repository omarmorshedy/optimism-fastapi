"""Typed application settings (Pydantic BaseSettings).

Single source of truth for every environment variable (see arc42 §5.2.1,
§8.5 and summary.md "Configurable constants"). Read once at startup and frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DEV_PASSWORD_HASH = (
    # bcrypt cost-12 hash of the string "change-me" — DEV/TEST ONLY.
    # Production must set ADMIN_PASSWORD_HASH from secret management.
    "$2b$12$.U8i3Rf76NvC9ZT3ZPFu7.Hn7SbUKcjHwoun6hSajUmLBJUtUFeAS"
)


@dataclass(frozen=True)
class RateLimitRule:
    """A parsed rate-limit rule: at most `limit` requests per `window_seconds`."""

    limit: int
    window_seconds: int


def parse_rate_limit(value: str, default_limit: int = 10) -> RateLimitRule:
    """Parse ``"N/unit"`` strings (``"10/minute"``, ``"60/second"``, ``"5/hour"``)."""
    value = value.strip()
    if "/" not in value:
        return RateLimitRule(limit=max(1, int(value)), window_seconds=60)
    raw_limit, unit = value.split("/", 1)
    limit = max(1, int(raw_limit))
    unit = unit.strip().lower()
    multipliers = {
        "second": 1,
        "sec": 1,
        "s": 1,
        "minute": 60,
        "min": 60,
        "m": 60,
        "hour": 3600,
        "hr": 3600,
        "h": 3600,
    }
    if unit not in multipliers:
        raise ValueError(f"Unknown rate-limit unit: {unit!r}")
    return RateLimitRule(limit=limit, window_seconds=multipliers[unit])


class Settings(BaseSettings):
    """Typed, validated, immutable application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- Application ---
    app_name: str = "Optimism"
    environment: str = "development"
    log_level: str = "INFO"
    auto_migrate: bool = True

    # --- Database ---
    database_url: str = "postgresql+psycopg://optimism:optimism@localhost:5432/optimism"

    # --- Admin authentication (ADR-005) ---
    admin_password_hash: str = Field(default=DEFAULT_DEV_PASSWORD_HASH)
    session_secret: str = "dev-only-insecure-session-secret-change-me"
    session_max_age_seconds: int = 3600

    # Docker-secret file variants (arc42 §7.2/§7.3): when *_FILE is set, the
    # file content wins over the plain value.
    admin_password_hash_file: str | None = None
    session_secret_file: str | None = None
    smtp_user_file: str | None = None
    smtp_pass_file: str | None = None

    @model_validator(mode="after")
    def _load_secret_files(self) -> Settings:
        for field, file_field in (
            ("admin_password_hash", "admin_password_hash_file"),
            ("session_secret", "session_secret_file"),
            ("smtp_user", "smtp_user_file"),
            ("smtp_pass", "smtp_pass_file"),
        ):
            path = getattr(self, file_field)
            if path:
                try:
                    with open(path, encoding="utf-8") as fh:
                        object.__setattr__(self, field, fh.read().strip())
                except OSError as exc:
                    raise ValueError(f"Cannot read secret file {path}: {exc}") from exc
        return self

    # --- Public site / email ---
    optimism_website_base_url: str = "http://localhost:8000"
    optimism_email_org_from_addr: str = "booking@example.org"
    optimism_email_org_notify_addr: str = "organisers@example.org"

    # --- SMTP (email outbox worker, ADR-010) ---
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_tls: bool = False
    email_worker_enabled: bool = True
    email_worker_poll_seconds: int = 10
    email_worker_alive_timeout_seconds: int = 60

    # --- Rate limits (per IP, decision #12) ---
    rate_limit_booking_create: str = "10/minute"
    rate_limit_booking_cancel: str = "10/minute"
    rate_limit_calendar_read: str = "60/minute"
    rate_limit_admin_login: str = "5/minute"

    # --- Booking rules (decision #6, ADR-009) ---
    booking_cancellation_cutoff_minutes: int = 5

    # --- Email retry policy (decision #13) ---
    email_retry_base_delay_seconds: int = 60
    email_retry_max_attempts: int = 5
    email_retry_max_delay_seconds: int = 960

    # --- Observability alerts (decision #14) ---
    observability_alert_5xx_rate: float = 0.01
    observability_alert_email_backlog: int = 100
    observability_alert_db_pool_exhaustion: bool = True

    @field_validator("booking_cancellation_cutoff_minutes")
    @classmethod
    def _cutoff_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("BOOKING_CANCELLATION_CUTOFF_MINUTES must be >= 0")
        return v

    @field_validator("email_retry_max_attempts")
    @classmethod
    def _retry_attempts_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("EMAIL_RETRY_MAX_ATTEMPTS must be >= 1")
        return v

    # --- Convenience accessors for parsed rate limits ---
    @property
    def booking_create_limit(self) -> RateLimitRule:
        return parse_rate_limit(self.rate_limit_booking_create)

    @property
    def booking_cancel_limit(self) -> RateLimitRule:
        return parse_rate_limit(self.rate_limit_booking_cancel)

    @property
    def calendar_read_limit(self) -> RateLimitRule:
        return parse_rate_limit(self.rate_limit_calendar_read)

    @property
    def admin_login_limit(self) -> RateLimitRule:
        return parse_rate_limit(self.rate_limit_admin_login)


@lru_cache
def get_settings() -> Settings:
    """Application-wide cached Settings instance (injected via Depends)."""
    return Settings()

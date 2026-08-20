"""Fixed-UTC time policy (ADR-007).

All booking datetimes are stored as ``timestamptz`` and serialised in UTC with a
``Z`` suffix; availability window times are ``HH:mm`` UTC clock times within a
single day; calendar dates are ``YYYY-MM-DD``. No DST/BST conversion ever.
"""

from __future__ import annotations

import datetime as dt

# Weekday convention preserved from legacy: Sunday = 0 .. Saturday = 6.
SUNDAY = 0
WEEKDAYS = range(7)


class TimeError(ValueError):
    """Raised for malformed dates/times (maps to a 422 problem response)."""


def utcnow() -> dt.datetime:
    """Current time as an aware UTC datetime."""
    return dt.datetime.now(dt.UTC)


def ensure_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Normalize a possibly-naive datetime (SQLite) to aware UTC (PG returns aware)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def utc_midnight(date: dt.date) -> dt.datetime:
    """Midnight (00:00:00) UTC of a calendar date."""
    return dt.datetime.combine(date, dt.time.min, tzinfo=dt.UTC)


def weekday_of(value: dt.datetime | dt.date) -> int:
    """Legacy weekday number: Sunday = 0 .. Saturday = 6."""
    return (value.weekday() + 1) % 7


def parse_datetime(value: str) -> dt.datetime:
    """Parse an ISO-8601 datetime; a value without an offset is treated as UTC.

    Raises TimeError on malformed input.
    """
    if not isinstance(value, str) or not value.strip():
        raise TimeError("Invalid datetime.")
    try:
        parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimeError("Invalid datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def parse_date(value: str) -> dt.date:
    """Parse a strict ISO-8601 calendar date; full datetime strings are accepted.

    Raises TimeError on malformed input.
    """
    if not isinstance(value, str) or not value.strip():
        raise TimeError("Invalid date.")
    stripped = value.strip()
    try:
        return dt.date.fromisoformat(stripped)
    except ValueError:
        pass
    # Full datetime strings are also accepted (spec §1.2).
    try:
        return parse_datetime(stripped).date()
    except TimeError as exc:
        raise TimeError("Invalid date.") from exc


def parse_window_time(value: str) -> dt.time:
    """Parse an ``HH:mm`` UTC clock time. Raises TimeError on malformed input."""
    if not isinstance(value, str):
        raise TimeError("Invalid time.")
    try:
        hour_str, minute_str = value.strip().split(":", 1)
        hour, minute = int(hour_str), int(minute_str)
        result = dt.time(hour=hour, minute=minute, tzinfo=dt.UTC)
    except (ValueError, TypeError) as exc:
        raise TimeError("Invalid time.") from exc
    return result


def serialize_datetime(value: dt.datetime) -> str:
    """Serialize an aware datetime as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (UTC, 3 ms digits)."""
    utc = value.astimezone(dt.UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def serialize_date(value: dt.date) -> str:
    return value.isoformat()


def serialize_window_time(value: dt.time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def combine_date_and_time(date: dt.date, clock_time: dt.time) -> dt.datetime:
    """Combine a calendar date with a UTC clock time (single-day assumption)."""
    return dt.datetime.combine(
        date, dt.time(hour=clock_time.hour, minute=clock_time.minute), tzinfo=dt.UTC
    )


def ranges_overlap(
    a_start: dt.datetime, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime
) -> bool:
    """Correct interval-overlap predicate (fixes the legacy boundary bug):
    ``a_start < b_end AND a_end > b_start``.
    """
    return a_start < b_end and a_end > b_start


def ordinal_day(day: int) -> str:
    """Moment.js-style ordinal for the day-of-month (1st, 2nd, 3rd, 4th, ...)."""
    suffix = "th" if 10 <= day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def format_moment_like(value: dt.datetime) -> str:
    """Format like ``moment(value).format('dddd, MMMM Do YYYY, h:mm a')`` in UTC.

    Preserves the legacy confirmation-email wording (ADR-015) while rendering in
    fixed UTC (ADR-007).
    """
    utc = value.astimezone(dt.UTC)
    hour12 = utc.hour % 12
    if hour12 == 0:
        hour12 = 12
    ampm = "am" if utc.hour < 12 else "pm"
    return (
        f"{utc.strftime('%A, %B')} {ordinal_day(utc.day)} {utc.year}, "
        f"{hour12}:{utc.minute:02d} {ampm}"
    )


def format_llll(value: dt.datetime) -> str:
    """Moment.js ``llll``-style formatting for the web UI (UTC)."""
    utc = value.astimezone(dt.UTC)
    hour12 = utc.hour % 12
    if hour12 == 0:
        hour12 = 12
    ampm = "am" if utc.hour < 12 else "pm"
    return f"{utc.strftime('%a, %b')} {utc.day}, {utc.year} {hour12}:{utc.minute:02d} {ampm}"

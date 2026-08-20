"""Unit tests for the fixed-UTC time policy and interval rules (ADR-007)."""

from __future__ import annotations

import datetime as dt

import pytest
from app.core.time import (
    TimeError,
    combine_date_and_time,
    format_llll,
    format_moment_like,
    ordinal_day,
    parse_date,
    parse_datetime,
    parse_window_time,
    ranges_overlap,
    serialize_datetime,
    serialize_window_time,
    utcnow,
    weekday_of,
)


class TestParseDatetime:
    def test_no_offset_means_utc(self) -> None:
        parsed = parse_datetime("2022-03-17T09:30:00")
        assert parsed.tzinfo == dt.UTC
        assert parsed == dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)

    def test_explicit_offset_converted_to_utc(self) -> None:
        parsed = parse_datetime("2022-03-17T10:30:00+01:00")
        assert parsed == dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)

    def test_z_suffix(self) -> None:
        parsed = parse_datetime("2022-03-17T09:30:00Z")
        assert parsed.tzinfo == dt.UTC

    def test_invalid_raises(self) -> None:
        with pytest.raises(TimeError):
            parse_datetime("not-a-date")


class TestParseDate:
    def test_strict_iso(self) -> None:
        assert parse_date("2022-03-17") == dt.date(2022, 3, 17)

    def test_full_datetime_accepted(self) -> None:
        assert parse_date("2022-03-17T09:30:00") == dt.date(2022, 3, 17)

    def test_invalid_month_rejected(self) -> None:
        with pytest.raises(TimeError):
            parse_date("2022-17-03")


class TestWindowTime:
    def test_parse_and_serialize_roundtrip(self) -> None:
        t = parse_window_time("09:30")
        assert serialize_window_time(t) == "09:30"

    def test_bad_time_raises(self) -> None:
        with pytest.raises(TimeError):
            parse_window_time("25:99")


class TestWeekday:
    def test_sunday_is_zero(self) -> None:
        assert weekday_of(dt.date(2022, 3, 20)) == 0  # Sunday

    def test_monday_is_one(self) -> None:
        assert weekday_of(dt.date(2022, 3, 21)) == 1  # Monday


class TestSerialization:
    def test_utc_z_with_millis(self) -> None:
        value = dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)
        assert serialize_datetime(value) == "2022-03-17T09:30:00.000Z"

    def test_millis_preserved(self) -> None:
        value = dt.datetime(2022, 3, 17, 9, 30, 0, 123000, tzinfo=dt.UTC)
        assert serialize_datetime(value) == "2022-03-17T09:30:00.123Z"

    def test_utc_midnight(self) -> None:
        assert serialize_datetime(combine_date_and_time(dt.date(2022, 3, 17), dt.time(0, 0))) == (
            "2022-03-17T00:00:00.000Z"
        )


class TestOverlap:
    def test_basic_overlap(self) -> None:
        assert ranges_overlap(
            dt.datetime(2022, 1, 1, 9, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 11, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 10, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 12, 0, tzinfo=dt.UTC),
        )

    def test_touching_boundaries_do_not_overlap(self) -> None:
        # a ends exactly when b starts -> no overlap (strict predicate).
        assert not ranges_overlap(
            dt.datetime(2022, 1, 1, 9, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 10, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 10, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 11, 0, tzinfo=dt.UTC),
        )

    def test_spanning_booking_overlaps(self) -> None:
        # A booking spanning the whole queried range must count (legacy bug fix).
        assert ranges_overlap(
            dt.datetime(2022, 1, 1, 9, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 12, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 8, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 1, 1, 13, 0, tzinfo=dt.UTC),
        )


class TestFormatting:
    def test_ordinal(self) -> None:
        assert ordinal_day(1) == "1st"
        assert ordinal_day(2) == "2nd"
        assert ordinal_day(3) == "3rd"
        assert ordinal_day(4) == "4th"
        assert ordinal_day(11) == "11th"
        assert ordinal_day(21) == "21st"

    def test_moment_like(self) -> None:
        value = dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)
        # Thursday, March 17th 2022, 9:30 am (moment 'dddd, MMMM Do YYYY, h:mm a')
        assert format_moment_like(value) == "Thursday, March 17th 2022, 9:30 am"

    def test_moment_like_pm(self) -> None:
        value = dt.datetime(2022, 3, 17, 15, 5, tzinfo=dt.UTC)
        assert format_moment_like(value) == "Thursday, March 17th 2022, 3:05 pm"

    def test_moment_like_midnight(self) -> None:
        value = dt.datetime(2022, 3, 17, 0, 0, tzinfo=dt.UTC)
        assert format_moment_like(value) == "Thursday, March 17th 2022, 12:00 am"

    def test_llll(self) -> None:
        value = dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)
        assert format_llll(value) == "Thu, Mar 17, 2022 9:30 am"


class TestUtcnow:
    def test_utcnow_is_aware_utc(self) -> None:
        now = utcnow()
        assert now.tzinfo == dt.UTC

"""Unit tests for the preserved confirmation email template (ADR-015, §8.1)."""

from __future__ import annotations

import datetime as dt

from app.integrations.email.template import compose_confirmation_email

STARTS = dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)
ENDS = dt.datetime(2022, 3, 17, 10, 0, tzinfo=dt.UTC)


class TestEmailTemplate:
    def test_subject(self) -> None:
        subject, _ = compose_confirmation_email(
            name="A Name",
            email="someone@example.org",
            notes="Some text",
            starts=STARTS,
            ends=ENDS,
            resource_name="Dinky",
            cancellation_url="http://localhost:8000/cancel-booking/tok123",
        )
        assert subject == "Booking Confirmation - Dinky"

    def test_body_with_notes(self) -> None:
        _, body = compose_confirmation_email(
            name="A Name",
            email="someone@example.org",
            notes="Some text",
            starts=STARTS,
            ends=ENDS,
            resource_name="Dinky",
            cancellation_url="http://localhost:8000/cancel-booking/tok123",
        )
        assert body == (
            "Welcome A Name!\n"
            "\n"
            "Your booking has been confirmed.\n"
            "\n"
            "Booking Details:\n"
            "- Resource: Dinky\n"
            "- Start: Thursday, March 17th 2022, 9:30 am\n"
            "- End: Thursday, March 17th 2022, 10:00 am\n"
            "- Notes: Some text\n"
            "\n"
            "If you need to cancel this booking, please use the following link:\n"
            "http://localhost:8000/cancel-booking/tok123\n"
            "\n"
            "Thank you for your booking!"
        )

    def test_body_without_notes_omits_line(self) -> None:
        _, body = compose_confirmation_email(
            name="A Name",
            email="someone@example.org",
            notes="",
            starts=STARTS,
            ends=ENDS,
            resource_name="Dinky",
            cancellation_url="http://localhost:8000/cancel-booking/tok123",
        )
        assert "- Notes:" not in body
        assert body.endswith("Thank you for your booking!")

    def test_utc_rendering_for_summer_date(self) -> None:
        # ADR-007: a summer date must render in UTC, not BST.
        _, body = compose_confirmation_email(
            name="A Name",
            email="someone@example.org",
            notes="",
            starts=dt.datetime(2022, 7, 1, 9, 30, tzinfo=dt.UTC),
            ends=dt.datetime(2022, 7, 1, 10, 0, tzinfo=dt.UTC),
            resource_name="Dinky",
            cancellation_url="http://localhost:8000/cancel-booking/tok123",
        )
        assert "- Start: Friday, July 1st 2022, 9:30 am" in body

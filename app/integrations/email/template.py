"""Booking confirmation email — subject and wording preserved verbatim (ADR-015,
decision #9); times rendered in fixed UTC (ADR-007, §11.8).

Template (API_SPEC §8.1):

    Welcome {name}!

    Your booking has been confirmed.

    Booking Details:
    - Resource: {resourceName}
    - Start: {startTime}
    - End: {endTime}
    [- Notes: {notes}]        (line present only when notes is non-empty)

    If you need to cancel this booking, please use the following link:
    {cancellationUrl}

    Thank you for your booking!
"""

from __future__ import annotations

import datetime as dt

from app.core.time import format_moment_like


def compose_confirmation_email(
    *,
    name: str,
    email: str,
    notes: str,
    starts: dt.datetime,
    ends: dt.datetime,
    resource_name: str,
    cancellation_url: str,
) -> tuple[str, str]:
    """Return ``(subject, body)`` matching the legacy wording exactly."""
    subject = f"Booking Confirmation - {resource_name}"
    start_time = format_moment_like(starts)
    end_time = format_moment_like(ends)
    notes_line = f"- Notes: {notes}" if notes else ""
    body = (
        f"Welcome {name}!\n"
        "\n"
        "Your booking has been confirmed.\n"
        "\n"
        "Booking Details:\n"
        f"- Resource: {resource_name}\n"
        f"- Start: {start_time}\n"
        f"- End: {end_time}\n"
        f"{notes_line}\n"
        "\n"
        "If you need to cancel this booking, please use the following link:\n"
        f"{cancellation_url}\n"
        "\n"
        "Thank you for your booking!"
    )
    return subject, body

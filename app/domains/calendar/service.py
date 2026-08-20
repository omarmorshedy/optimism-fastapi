"""Calendar availability algorithm (API_SPEC §6).

Response shape identical to the legacy calendar endpoint:

    {"dates": [{"date": "2022-03-17T00:00:00.000Z",
                "resources": [{"resourceName": "...",
                               "slots": [{"starts": "...", "ends": "...", "status": "available"}]}]}]}
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import not_found, validation_error
from app.core.time import (
    combine_date_and_time,
    ensure_utc,
    ranges_overlap,
    serialize_datetime,
    utc_midnight,
    weekday_of,
)
from app.domains.bookings.repository import BookingRepository
from app.domains.windows.repository import (
    AvailabilityExceptionRepository,
    AvailabilityWindowRepository,
)
from app.models.availability_exception import AvailabilityException
from app.models.availability_window import AvailabilityWindow

DETAIL_END_BEFORE_START = "The end date must be after the start date."


class CalendarService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.window_repo = AvailabilityWindowRepository(session)
        self.exception_repo = AvailabilityExceptionRepository(session)
        self.booking_repo = BookingRepository(session)

    def get(self, start_date: dt.date, end_date: dt.date, resource_id: int) -> dict[str, Any]:
        if end_date <= start_date:
            raise validation_error(DETAIL_END_BEFORE_START)

        resource = self.booking_repo.get_resource(resource_id)
        if resource is None:
            raise not_found("No such resource.")

        windows = self.window_repo.list_for_resource(resource_id)
        exceptions = self.exception_repo.list_covering_range(resource_id, start_date, end_date)
        range_start = utc_midnight(start_date)
        range_end = utc_midnight(end_date + dt.timedelta(days=1))
        # Correct overlap predicate against the range (fixes the legacy boundary
        # bug: starts < rangeEnd AND ends > rangeStart).
        bookings = self.booking_repo.list_active_overlapping(resource_id, range_start, range_end)

        dates: list[dict[str, Any]] = []
        day = start_date
        while day <= end_date:
            day_windows = self._effective_windows(windows, exceptions, day)
            slots = []
            for window in day_windows:
                instance_starts = combine_date_and_time(day, window.starts)
                instance_ends = combine_date_and_time(day, window.ends)
                count = sum(
                    1
                    for b in bookings
                    if ranges_overlap(
                        ensure_utc(b.starts) or instance_starts,
                        ensure_utc(b.ends) or instance_ends,
                        instance_starts,
                        instance_ends,
                    )
                )
                status = "available" if count < resource.capacity else "unavailable"
                slots.append(
                    {
                        "starts": serialize_datetime(instance_starts),
                        "ends": serialize_datetime(instance_ends),
                        "status": status,
                    }
                )
            dates.append(
                {
                    "date": serialize_datetime(utc_midnight(day)),
                    "resources": [{"resourceName": resource.name, "slots": slots}],
                }
            )
            day += dt.timedelta(days=1)

        return {"dates": dates}

    def _effective_windows(
        self,
        windows: list[AvailabilityWindow],
        exceptions: list[AvailabilityException],
        day: dt.date,
    ) -> list[AvailabilityWindow]:
        weekday = weekday_of(day)
        day_windows = [w for w in windows if w.weekday == weekday]
        closed = any(e.kind == "closed" for e in exceptions if e.start_date <= day <= e.end_date)
        open_ = any(e.kind == "open" for e in exceptions if e.start_date <= day <= e.end_date)
        if closed and not open_:
            return []
        return day_windows

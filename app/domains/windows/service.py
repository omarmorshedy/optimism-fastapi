"""Business rules for availability windows and exceptions (API_SPEC §4.4)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from app.core.exceptions import conflict, not_found
from app.core.time import parse_window_time
from app.domains.resources.repository import ResourceRepository
from app.domains.windows.repository import (
    AvailabilityExceptionRepository,
    AvailabilityWindowRepository,
)
from app.domains.windows.schemas import (
    AvailabilityExceptionCreate,
    AvailabilityExceptionRead,
    AvailabilityExceptionUpdate,
    AvailabilityWindowCreate,
    AvailabilityWindowRead,
    AvailabilityWindowUpdate,
    WindowReplacementItem,
)

DETAIL_WINDOW_OVERLAP = "Overlapping availability window for this resource and weekday."
DETAIL_EXCEPTION_OVERLAP = "Overlapping availability exception range for this resource."
DETAIL_NO_SUCH_WINDOW = "No such availability window"
DETAIL_NO_SUCH_EXCEPTION = "No such availability exception"


def _times_overlap(a_starts: dt.time, a_ends: dt.time, b_starts: dt.time, b_ends: dt.time) -> bool:
    """Strict half-open overlap for same-day windows (matches the booking
    predicate). Compares (hour, minute) so SQLite's tz-naive times behave
    identically to PostgreSQL's tz-aware times."""
    return (a_starts.hour, a_starts.minute) < (b_ends.hour, b_ends.minute) and (
        a_ends.hour,
        a_ends.minute,
    ) > (b_starts.hour, b_starts.minute)


class AvailabilityWindowService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AvailabilityWindowRepository(session)
        self.resource_repo = ResourceRepository(session)

    def _require_resource(self, resource_id: int) -> None:
        if self.resource_repo.get(resource_id) is None:
            raise not_found("Resource not found.")

    def _check_overlap(
        self,
        *,
        resource_id: int,
        weekday: int,
        starts: dt.time,
        ends: dt.time,
        exclude_id: int | None = None,
    ) -> None:
        for existing in self.repo.list_for_weekday(resource_id, weekday):
            if existing.id == exclude_id:
                continue
            if _times_overlap(starts, ends, existing.starts, existing.ends):
                raise conflict(DETAIL_WINDOW_OVERLAP)

    def list_all(self, resource_id: int | None = None) -> list[AvailabilityWindowRead]:
        return [AvailabilityWindowRead.model_validate(w) for w in self.repo.list_all(resource_id)]

    def list_for_resource(self, resource_id: int) -> list[AvailabilityWindowRead]:
        self._require_resource(resource_id)
        return [
            AvailabilityWindowRead.model_validate(w)
            for w in self.repo.list_for_resource(resource_id)
        ]

    def get(self, window_id: int) -> AvailabilityWindowRead:
        obj = self.repo.get(window_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_WINDOW)
        return AvailabilityWindowRead.model_validate(obj)

    def create(self, data: AvailabilityWindowCreate) -> AvailabilityWindowRead:
        self._require_resource(data.resource_id)
        starts = parse_window_time(data.starts)
        ends = parse_window_time(data.ends)
        self._check_overlap(
            resource_id=data.resource_id, weekday=data.weekday, starts=starts, ends=ends
        )
        obj = self.repo.create(
            resource_id=data.resource_id,
            weekday=data.weekday,
            starts=starts,
            ends=ends,
            name=data.name,
        )
        self.session.flush()
        return AvailabilityWindowRead.model_validate(obj)

    def update(self, window_id: int, data: AvailabilityWindowUpdate) -> AvailabilityWindowRead:
        obj = self.repo.get(window_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_WINDOW)
        fields = data.model_dump(exclude_unset=True)
        if "resource_id" in fields:
            self._require_resource(fields["resource_id"])
        starts = parse_window_time(fields["starts"]) if "starts" in fields else obj.starts
        ends = parse_window_time(fields["ends"]) if "ends" in fields else obj.ends
        if (ends.hour, ends.minute) <= (starts.hour, starts.minute):
            raise conflict("End time must be after start time.")
        resource_id = fields.get("resource_id", obj.resource_id)
        weekday = fields.get("weekday", obj.weekday)
        self._check_overlap(
            resource_id=resource_id,
            weekday=weekday,
            starts=starts,
            ends=ends,
            exclude_id=window_id,
        )
        if "starts" in fields:
            fields["starts"] = starts
        if "ends" in fields:
            fields["ends"] = ends
        if fields:
            self.repo.update(obj, **fields)
            self.session.flush()
        return AvailabilityWindowRead.model_validate(obj)

    def delete(self, window_id: int) -> None:
        obj = self.repo.get(window_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_WINDOW)
        self.repo.delete(obj)
        self.session.flush()

    def replace_for_resource(self, resource_id: int, items: list[WindowReplacementItem]) -> None:
        """Replace all windows for a resource (PUT /resources/{id}/windows, §4.2)."""
        self._require_resource(resource_id)
        parsed: list[tuple[int, dt.time, dt.time, str | None]] = []
        for item in items:
            starts = parse_window_time(item.starts)
            ends = parse_window_time(item.ends)
            parsed.append((item.weekday, starts, ends, item.name))
        # Validate the replacement set is internally non-overlapping.
        for i, (weekday, starts, ends, _) in enumerate(parsed):
            for weekday2, starts2, ends2, _ in parsed[i + 1 :]:
                if weekday == weekday2 and _times_overlap(starts, ends, starts2, ends2):
                    raise conflict(DETAIL_WINDOW_OVERLAP)
        windows = [
            self.repo.create(resource_id=resource_id, weekday=w, starts=s, ends=e, name=n)
            for w, s, e, n in parsed
        ]
        self.repo.replace_for_resource(resource_id, windows)
        self.session.flush()


class AvailabilityExceptionService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AvailabilityExceptionRepository(session)
        self.resource_repo = ResourceRepository(session)

    def _require_resource(self, resource_id: int) -> None:
        if self.resource_repo.get(resource_id) is None:
            raise not_found("Resource not found.")

    def _check_overlap(
        self,
        *,
        resource_id: int,
        start_date: dt.date,
        end_date: dt.date,
        exclude_id: int | None = None,
    ) -> None:
        if self.repo.list_overlapping_range(resource_id, start_date, end_date, exclude_id):
            raise conflict(DETAIL_EXCEPTION_OVERLAP)

    def list_all(self, resource_id: int | None = None) -> list[AvailabilityExceptionRead]:
        return [
            AvailabilityExceptionRead.model_validate(e) for e in self.repo.list_all(resource_id)
        ]

    def get(self, exception_id: int) -> AvailabilityExceptionRead:
        obj = self.repo.get(exception_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_EXCEPTION)
        return AvailabilityExceptionRead.model_validate(obj)

    def create(self, data: AvailabilityExceptionCreate) -> AvailabilityExceptionRead:
        self._require_resource(data.resource_id)
        self._check_overlap(
            resource_id=data.resource_id, start_date=data.start_date, end_date=data.end_date
        )
        obj = self.repo.create(
            resource_id=data.resource_id,
            start_date=data.start_date,
            end_date=data.end_date,
            kind=data.kind,
            reason=data.reason,
        )
        self.session.flush()
        return AvailabilityExceptionRead.model_validate(obj)

    def update(
        self, exception_id: int, data: AvailabilityExceptionUpdate
    ) -> AvailabilityExceptionRead:
        obj = self.repo.get(exception_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_EXCEPTION)
        fields = data.model_dump(exclude_unset=True)
        if "resource_id" in fields:
            self._require_resource(fields["resource_id"])
        if "start_date" in fields or "end_date" in fields:
            start = fields.get("start_date", obj.start_date)
            end = fields.get("end_date", obj.end_date)
            if end < start:
                raise conflict("End date must not be before start date.")
            resource_id = fields.get("resource_id", obj.resource_id)
            self._check_overlap(
                resource_id=resource_id,
                start_date=start,
                end_date=end,
                exclude_id=exception_id,
            )
        if fields:
            self.repo.update(obj, **fields)
            self.session.flush()
        return AvailabilityExceptionRead.model_validate(obj)

    def delete(self, exception_id: int) -> None:
        obj = self.repo.get(exception_id)
        if obj is None:
            raise not_found(DETAIL_NO_SUCH_EXCEPTION)
        self.repo.delete(obj)
        self.session.flush()

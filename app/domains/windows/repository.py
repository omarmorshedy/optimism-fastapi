"""Repository layer for availability windows and exceptions."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.availability_exception import AvailabilityException
from app.models.availability_window import AvailabilityWindow


class AvailabilityWindowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self, resource_id: int | None = None) -> list[AvailabilityWindow]:
        stmt = select(AvailabilityWindow).order_by(
            AvailabilityWindow.resource_id, AvailabilityWindow.weekday, AvailabilityWindow.starts
        )
        if resource_id is not None:
            stmt = stmt.where(AvailabilityWindow.resource_id == resource_id)
        return list(self.session.scalars(stmt))

    def get(self, window_id: int) -> AvailabilityWindow | None:
        return self.session.get(AvailabilityWindow, window_id)

    def list_for_resource(self, resource_id: int) -> list[AvailabilityWindow]:
        return self.list_all(resource_id=resource_id)

    def list_for_weekday(self, resource_id: int, weekday: int) -> list[AvailabilityWindow]:
        stmt = select(AvailabilityWindow).where(
            AvailabilityWindow.resource_id == resource_id,
            AvailabilityWindow.weekday == weekday,
        )
        return list(self.session.scalars(stmt))

    def create(
        self, *, resource_id: int, weekday: int, starts: dt.time, ends: dt.time, name: str | None
    ) -> AvailabilityWindow:
        obj = AvailabilityWindow(
            resource_id=resource_id, weekday=weekday, starts=starts, ends=ends, name=name
        )
        self.session.add(obj)
        return obj

    def update(self, obj: AvailabilityWindow, **fields: object) -> AvailabilityWindow:
        for key, value in fields.items():
            setattr(obj, key, value)
        return obj

    def delete(self, obj: AvailabilityWindow) -> None:
        self.session.delete(obj)

    def replace_for_resource(self, resource_id: int, windows: list[AvailabilityWindow]) -> None:
        """Delete all windows for a resource and insert the replacement set."""
        from sqlalchemy import delete

        self.session.execute(
            delete(AvailabilityWindow).where(AvailabilityWindow.resource_id == resource_id)
        )
        self.session.add_all(windows)


class AvailabilityExceptionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self, resource_id: int | None = None) -> list[AvailabilityException]:
        stmt = select(AvailabilityException).order_by(
            AvailabilityException.resource_id,
            AvailabilityException.start_date,
            AvailabilityException.end_date,
        )
        if resource_id is not None:
            stmt = stmt.where(AvailabilityException.resource_id == resource_id)
        return list(self.session.scalars(stmt))

    def get(self, exception_id: int) -> AvailabilityException | None:
        return self.session.get(AvailabilityException, exception_id)

    def list_overlapping_range(
        self,
        resource_id: int,
        start_date: dt.date,
        end_date: dt.date,
        exclude_id: int | None = None,
    ) -> list[AvailabilityException]:
        """Inclusive-range overlap: a.start <= b.end AND a.end >= b.start."""
        stmt = select(AvailabilityException).where(
            AvailabilityException.resource_id == resource_id,
            AvailabilityException.start_date <= end_date,
            AvailabilityException.end_date >= start_date,
        )
        if exclude_id is not None:
            stmt = stmt.where(AvailabilityException.id != exclude_id)
        return list(self.session.scalars(stmt))

    def list_covering_range(
        self, resource_id: int, start_date: dt.date, end_date: dt.date
    ) -> list[AvailabilityException]:
        stmt = select(AvailabilityException).where(
            AvailabilityException.resource_id == resource_id,
            AvailabilityException.start_date <= end_date,
            AvailabilityException.end_date >= start_date,
        )
        return list(self.session.scalars(stmt))

    def create(
        self,
        *,
        resource_id: int,
        start_date: dt.date,
        end_date: dt.date,
        kind: str,
        reason: str | None,
    ) -> AvailabilityException:
        obj = AvailabilityException(
            resource_id=resource_id,
            start_date=start_date,
            end_date=end_date,
            kind=kind,
            reason=reason,
        )
        self.session.add(obj)
        return obj

    def update(self, obj: AvailabilityException, **fields: object) -> AvailabilityException:
        for key, value in fields.items():
            setattr(obj, key, value)
        return obj

    def delete(self, obj: AvailabilityException) -> None:
        self.session.delete(obj)

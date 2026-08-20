"""Typed test-data factories (plan §1: factories; no shared magic ids)."""

from __future__ import annotations

import datetime as dt

from app.core.security import generate_token, hash_token
from app.models.availability_exception import AvailabilityException
from app.models.availability_window import AvailabilityWindow
from app.models.booking import Booking
from app.models.resource import Resource
from app.models.resource_type import ResourceType
from sqlalchemy.orm import Session

MONDAY = 1  # weekday convention: Sunday=0 … Saturday=6


def create_resource_type(session: Session, name: str = "room") -> ResourceType:
    obj = ResourceType(name=name)
    session.add(obj)
    session.flush()
    return obj


def create_resource(
    session: Session,
    name: str = "Dinky",
    capacity: int = 1,
    resource_type_id: int | None = None,
) -> Resource:
    obj = Resource(resource_type_id=resource_type_id, name=name, capacity=capacity)
    session.add(obj)
    session.flush()
    return obj


def create_window(
    session: Session,
    resource_id: int,
    weekday: int = MONDAY,
    starts: dt.time = dt.time(9, 30, tzinfo=dt.UTC),
    ends: dt.time = dt.time(10, 0, tzinfo=dt.UTC),
    name: str | None = None,
) -> AvailabilityWindow:
    obj = AvailabilityWindow(
        resource_id=resource_id, weekday=weekday, starts=starts, ends=ends, name=name
    )
    session.add(obj)
    session.flush()
    return obj


def create_exception(
    session: Session,
    resource_id: int,
    start_date: dt.date,
    end_date: dt.date | None = None,
    kind: str = "closed",
    reason: str | None = None,
) -> AvailabilityException:
    obj = AvailabilityException(
        resource_id=resource_id,
        start_date=start_date,
        end_date=end_date or start_date,
        kind=kind,
        reason=reason,
    )
    session.add(obj)
    session.flush()
    return obj


def create_booking(
    session: Session,
    resource_id: int,
    starts: dt.datetime,
    ends: dt.datetime,
    email: str = "someone@example.org",
    name: str = "A Name",
    notes: str = "Some text",
    cancelled: bool = False,
    with_token: bool = True,
) -> Booking:
    obj = Booking(
        resource_id=resource_id,
        email=email,
        name=name,
        notes=notes,
        starts=starts,
        ends=ends,
        cancelled=cancelled,
        token_hash=hash_token(generate_token()) if with_token else None,
    )
    session.add(obj)
    session.flush()
    return obj


def utc_datetime(year: int, month: int, day: int, hour: int = 9, minute: int = 30) -> dt.datetime:
    return dt.datetime(year, month, day, hour, minute, tzinfo=dt.UTC)

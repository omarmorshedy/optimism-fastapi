"""Pydantic schemas for bookings (API_SPEC §2.1, §3.4-3.7, §4.5)."""

from __future__ import annotations

import datetime as dt

from pydantic import EmailStr, Field, field_validator, model_validator

from app.core.exceptions import validation_error
from app.core.time import serialize_datetime
from app.domains.schemas_base import CamelModel, CamelReadModel


def _non_blank_name(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise validation_error("Name must not be blank.")
    return stripped


class BookingCreate(CamelModel):
    resource_id: int
    email: EmailStr
    name: str = Field(max_length=255)
    notes: str = Field(max_length=2000)
    starts: str
    ends: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return _non_blank_name(v)


class BookingRead(CamelReadModel):
    """Booking serialization — the token is NEVER present (improvement #8)."""

    id: int
    resource_id: int
    email: str
    name: str
    notes: str
    starts: str
    ends: str
    cancelled: bool
    created_at: str

    @field_validator("starts", "ends", "created_at", mode="before")
    @classmethod
    def _serialize_dt(cls, v: object) -> object:
        if isinstance(v, dt.datetime):
            return serialize_datetime(v)
        return v


class BookingWithResourceName(BookingRead):
    resource_name: str


class BookingCreated(BookingWithResourceName):
    """POST /bookings response — the raw token is returned exactly once."""

    token: str


class BookingAmend(CamelModel):
    """Token-authenticated amendment (API_SPEC §3.6)."""

    name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    notes: str | None = Field(default=None, max_length=2000)
    starts: str | None = None
    ends: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return _non_blank_name(v) if v is not None else None

    @model_validator(mode="after")
    def _both_or_neither_times(self) -> BookingAmend:
        if (self.starts is None) != (self.ends is None):
            raise validation_error("Both start and end times must be provided together.")
        return self


class BookingCancelResponse(CamelModel):
    message: str
    booking: BookingWithResourceName


class AdminBookingUpdate(BookingAmend):
    """Admin amend — same shape as user amend; cutoff does not apply."""


class BookingListFilter(CamelModel):
    """Query parameters for the admin bookings list (API_SPEC §4.5)."""

    resource_id: int | None = None
    cancelled: bool | None = None
    email: str | None = None
    starts_from: str | None = None
    starts_to: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

"""Pydantic schemas for availability windows and exceptions (API_SPEC §2.1, §4.4)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.core.exceptions import validation_error
from app.core.time import parse_window_time, serialize_window_time
from app.domains.schemas_base import CamelModel, CamelReadModel


class AvailabilityWindowBase(CamelModel):
    resource_id: int
    weekday: int = Field(ge=0, le=6)
    starts: str
    ends: str
    name: str | None = Field(default=None, max_length=255)

    @field_validator("starts", "ends")
    @classmethod
    def _times(cls, v: str) -> str:
        parse_window_time(v)  # raises TimeError -> validation
        return v

    @model_validator(mode="after")
    def _ends_after_starts(self) -> AvailabilityWindowBase:
        starts = parse_window_time(self.starts)
        ends = parse_window_time(self.ends)
        if ends <= starts:
            raise validation_error("End time must be after start time.")
        return self


class AvailabilityWindowCreate(AvailabilityWindowBase):
    pass


class AvailabilityWindowUpdate(CamelModel):
    resource_id: int | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    starts: str | None = None
    ends: str | None = None
    name: str | None = Field(default=None, max_length=255)

    @field_validator("starts", "ends")
    @classmethod
    def _times(cls, v: str | None) -> str | None:
        if v is not None:
            parse_window_time(v)
        return v


class AvailabilityWindowRead(CamelReadModel):
    id: int
    resource_id: int
    weekday: int
    starts: str
    ends: str
    name: str | None

    @field_validator("starts", "ends", mode="before")
    @classmethod
    def _serialize_time(cls, v: object) -> object:
        if isinstance(v, dt.time):
            return serialize_window_time(v)
        return v


class WindowReplacementItem(CamelModel):
    """One entry of the PUT /resources/{id}/windows replacement body (no ids)."""

    weekday: int = Field(ge=0, le=6)
    starts: str
    ends: str
    name: str | None = Field(default=None, max_length=255)

    @field_validator("starts", "ends")
    @classmethod
    def _times(cls, v: str) -> str:
        parse_window_time(v)
        return v

    @model_validator(mode="after")
    def _ends_after_starts(self) -> WindowReplacementItem:
        starts = parse_window_time(self.starts)
        ends = parse_window_time(self.ends)
        if ends <= starts:
            raise validation_error("End time must be after start time.")
        return self


class AvailabilityExceptionBase(CamelModel):
    resource_id: int
    start_date: dt.date
    end_date: dt.date
    kind: Literal["closed", "open"]
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _range_non_empty(self) -> AvailabilityExceptionBase:
        if self.end_date < self.start_date:
            raise validation_error("End date must not be before start date.")
        return self


class AvailabilityExceptionCreate(AvailabilityExceptionBase):
    pass


class AvailabilityExceptionUpdate(CamelModel):
    resource_id: int | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    kind: Literal["closed", "open"] | None = None
    reason: str | None = Field(default=None, max_length=500)


class AvailabilityExceptionRead(AvailabilityExceptionBase, CamelReadModel):
    id: int

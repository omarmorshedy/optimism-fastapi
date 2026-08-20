"""AvailabilityWindow model — one recurring fixed UTC window per resource/weekday (ADR-008)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Time, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.resource import Resource


class AvailabilityWindow(Base):
    __tablename__ = "availability_windows"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("ends > starts", name="ends_after_starts"),
        UniqueConstraint("resource_id", "weekday", "starts", "ends", name="uq_window_instance"),
        # The overlap exclusion constraint (no overlapping windows for the same
        # resource+weekday) is created in the Alembic migration with raw
        # PostgreSQL DDL (see migrations/versions/0001_initial.py).
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weekday: Mapped[int] = mapped_column(nullable=False, index=True)
    starts: Mapped[dt.time] = mapped_column(Time(timezone=True), nullable=False)
    ends: Mapped[dt.time] = mapped_column(Time(timezone=True), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    resource: Mapped[Resource] = relationship(back_populates="windows")

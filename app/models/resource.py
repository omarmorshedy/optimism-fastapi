"""Resource model — a bookable place/item (room, laser cutter, hot desk)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.availability_exception import AvailabilityException
    from app.models.availability_window import AvailabilityWindow
    from app.models.booking import Booking
    from app.models.resource_type import ResourceType


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint("length(trim(name)) > 0", name="name_non_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_types.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    resource_type: Mapped[ResourceType | None] = relationship(back_populates="resources")
    windows: Mapped[list[AvailabilityWindow]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    exceptions: Mapped[list[AvailabilityException]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    bookings: Mapped[list[Booking]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )

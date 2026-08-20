"""Booking model — the durable record of a dated reservation.

Capacity semantics (ADR-006): each active booking consumes exactly one unit of
a window's capacity. The raw cancellation token is never stored; only its hash
is (unique). Admin deletes are soft (deleted_at set, counts as cancelled).
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.resource import Resource


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("starts < ends", name="ends_after_starts"),
        CheckConstraint("length(trim(name)) > 0", name="name_non_blank"),
        CheckConstraint("length(trim(email)) > 0", name="email_non_blank"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    starts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    # SHA-256 hash of the 32-byte random cancellation token; never the raw token.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    resource: Mapped[Resource] = relationship(back_populates="bookings")

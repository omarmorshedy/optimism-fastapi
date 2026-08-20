"""AuditEvent model — append-only record of administrative actions (decision #2)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JSONType = JSON().with_variant(JSONB, "postgresql")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="shared_admin")
    resource_id: Mapped[int | None] = mapped_column(nullable=True)
    booking_id: Mapped[int | None] = mapped_column(nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failure
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

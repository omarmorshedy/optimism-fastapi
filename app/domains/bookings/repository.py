"""Repository layer for bookings and the email outbox."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.email_outbox import EmailOutbox
from app.models.resource import Resource


class BookingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, booking_id: int) -> Booking | None:
        return self.session.get(Booking, booking_id)

    def get_by_token_hash(self, token_hash: str) -> Booking | None:
        stmt = select(Booking).where(Booking.token_hash == token_hash)
        return self.session.scalar(stmt)

    def get_resource(self, resource_id: int) -> Resource | None:
        return self.session.get(Resource, resource_id)

    def list_active_overlapping(
        self, resource_id: int, start: dt.datetime, end: dt.datetime, exclude_id: int | None = None
    ) -> list[Booking]:
        """Active (non-cancelled, non-deleted) bookings overlapping [start, end)
        using the corrected predicate: existing.starts < end AND existing.ends > start.
        """
        stmt = (
            select(Booking)
            .where(Booking.resource_id == resource_id)
            .where(Booking.cancelled.is_(False))
            .where(Booking.deleted_at.is_(None))
            .where(Booking.starts < end)
            .where(Booking.ends > start)
        )
        if exclude_id is not None:
            stmt = stmt.where(Booking.id != exclude_id)
        return list(self.session.scalars(stmt))

    def count_active_overlapping(
        self, resource_id: int, start: dt.datetime, end: dt.datetime, exclude_id: int | None = None
    ) -> int:
        stmt = (
            select(func.count(Booking.id))
            .where(Booking.resource_id == resource_id)
            .where(Booking.cancelled.is_(False))
            .where(Booking.deleted_at.is_(None))
            .where(Booking.starts < end)
            .where(Booking.ends > start)
        )
        if exclude_id is not None:
            stmt = stmt.where(Booking.id != exclude_id)
        return int(self.session.scalar(stmt) or 0)

    def create(self, **fields: object) -> Booking:
        obj = Booking(**fields)
        self.session.add(obj)
        return obj

    def update(self, obj: Booking, **fields: object) -> Booking:
        for key, value in fields.items():
            setattr(obj, key, value)
        return obj

    def delete(self, obj: Booking) -> None:
        self.session.delete(obj)

    def list_filtered(
        self,
        *,
        resource_id: int | None,
        cancelled: bool | None,
        email: str | None,
        starts_from: dt.datetime | None,
        starts_to: dt.datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Booking], int]:
        conditions = []
        if resource_id is not None:
            conditions.append(Booking.resource_id == resource_id)
        if cancelled is not None:
            conditions.append(Booking.cancelled.is_(cancelled))
        if email:
            conditions.append(Booking.email.ilike(f"%{email}%"))
        if starts_from is not None:
            conditions.append(Booking.starts >= starts_from)
        if starts_to is not None:
            conditions.append(Booking.starts <= starts_to)

        count_stmt = select(func.count(Booking.id)).where(*conditions)
        total = int(self.session.scalar(count_stmt) or 0)

        stmt = (
            select(Booking)
            .where(*conditions)
            .order_by(Booking.starts.desc(), Booking.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt)), total


class EmailOutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(
        self,
        *,
        booking_id: int,
        subject: str,
        body: str,
        from_addr: str,
        to_addr: str,
        bcc_addr: str | None,
    ) -> EmailOutbox:
        obj = EmailOutbox(
            booking_id=booking_id,
            status="pending",
            attempts=0,
            subject=subject,
            body=body,
            from_addr=from_addr,
            to_addr=to_addr,
            bcc_addr=bcc_addr,
        )
        self.session.add(obj)
        return obj

    def pending_count(self) -> int:
        stmt = select(func.count(EmailOutbox.id)).where(
            EmailOutbox.status.in_(("pending", "failed"))
        )
        return int(self.session.scalar(stmt) or 0)

    def claim_batch(self, limit: int = 20, *, for_update: bool = False) -> list[EmailOutbox]:
        """Claim entries awaiting delivery: pending or failed-with-backoff-due.
        Failed entries are re-claimable once their next_attempt_at passes
        (ADR-010 retry policy)."""
        stmt = (
            select(EmailOutbox)
            .where(EmailOutbox.status.in_(("pending", "failed")))
            .where(
                (EmailOutbox.next_attempt_at.is_(None))
                | (EmailOutbox.next_attempt_at <= func.now())
            )
            .order_by(EmailOutbox.id)
            .limit(limit)
        )
        if for_update:
            stmt = stmt.with_for_update(skip_locked=True)
        return list(self.session.scalars(stmt))

    def mark_sent(self, obj: EmailOutbox) -> None:
        obj.status = "sent"
        obj.sent_at = dt.datetime.now(dt.UTC)
        obj.last_error = None

    def record_failure(self, obj: EmailOutbox, error: str, *, attempts: int) -> None:
        obj.attempts = attempts
        obj.last_error = error[:2000]

    def mark_dead_letter(self, obj: EmailOutbox) -> None:
        obj.status = "dead_letter"

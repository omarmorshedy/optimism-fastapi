"""Booking service — the core business rules (API_SPEC §5, §7).

Includes the exact-window matching, availability-exception application,
advisory-locked transactional capacity check (ADR-006, no overbooking),
hashed cancellation tokens, idempotent cancellation, token amendment with
cutoff enforcement, admin operations, soft delete, and email outbox enqueue.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    DETAIL_END_AFTER_START,
    DETAIL_NO_BOOKING_WITH_TOKEN,
    DETAIL_SLOT_FULL,
    conflict,
    not_found,
    validation_error,
)
from app.core.security import generate_token, hash_token
from app.core.time import (
    ensure_utc,
    parse_datetime,
    utcnow,
    weekday_of,
)
from app.domains.bookings.repository import BookingRepository, EmailOutboxRepository
from app.domains.bookings.schemas import (
    AdminBookingUpdate,
    BookingAmend,
    BookingCancelResponse,
    BookingCreate,
    BookingCreated,
    BookingListFilter,
    BookingRead,
    BookingWithResourceName,
)
from app.domains.windows.repository import (
    AvailabilityExceptionRepository,
    AvailabilityWindowRepository,
)
from app.integrations.email.template import compose_confirmation_email
from app.models.availability_window import AvailabilityWindow
from app.models.booking import Booking

DETAIL_WINDOW_MISMATCH = "Booking times must exactly match an availability window."
DETAIL_UNAVAILABLE_DATE = "This time slot is not available on the requested date."
DETAIL_CUTOFF_PASSED = "This booking can no longer be changed or cancelled because it has started or is about to start (cancellation cutoff reached)."
DETAIL_CANCELLED_AMEND = "This booking has been cancelled and cannot be amended."
DETAIL_AMEND_MESSAGE = "Booking amended successfully."
DETAIL_SOFT_DELETED = "Booking deleted."


def resolve_public_base_url(configured_base: str, request_base: str) -> str:
    """Choose the base URL for emailed cancellation links.

    If the configured website URL is still the local development default, use
    the origin the booking request actually came from so links work when the
    app is reached through a different host/port/proxy. An explicit non-local
    OPTIMISM_WEBSITE_BASE_URL is preserved.
    """
    configured = configured_base.rstrip("/")
    host = urlparse(configured).hostname
    if host in ("localhost", "127.0.0.1"):
        return request_base
    return configured


class BookingService:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings
        self.repo = BookingRepository(session)
        self.window_repo = AvailabilityWindowRepository(session)
        self.exception_repo = AvailabilityExceptionRepository(session)
        self.outbox_repo = EmailOutboxRepository(session)

    # --- helpers -------------------------------------------------------------

    def _effective_windows_for_date(
        self, resource_id: int, date: dt.date
    ) -> list[AvailabilityWindow]:
        """Recurring windows of the date's weekday, minus `closed` exceptions,
        re-added by `open` exceptions (decision #5; see implementation log)."""
        weekday = weekday_of(date)
        windows = self.window_repo.list_for_weekday(resource_id, weekday)
        exceptions = self.exception_repo.list_covering_range(resource_id, date, date)
        closed = any(e.kind == "closed" for e in exceptions)
        open_ = any(e.kind == "open" for e in exceptions)
        if closed and not open_:
            return []
        return windows

    def _match_window(
        self, resource_id: int, starts: dt.datetime, ends: dt.datetime
    ) -> AvailabilityWindow | None:
        """Exactly one AvailabilityWindow must match the requested times.

        Ignores exceptions — a match here means the times are structurally
        valid; exception removal is checked separately (so a closed date is a
        409, not a 422, per API_SPEC §5.4).
        """
        windows = self.window_repo.list_for_weekday(resource_id, weekday_of(starts.date()))
        matches = [
            w
            for w in windows
            if w.starts.hour == starts.hour
            and w.starts.minute == starts.minute
            and w.ends.hour == ends.hour
            and w.ends.minute == ends.minute
        ]
        return matches[0] if len(matches) == 1 else None

    def _ensure_date_available(
        self, resource_id: int, starts: dt.datetime, window: AvailabilityWindow
    ) -> None:
        """409 when a closed exception removes the matched window on that date."""
        effective = self._effective_windows_for_date(resource_id, starts.date())
        if window not in effective:
            raise conflict(DETAIL_UNAVAILABLE_DATE)
        return None

    def _advisory_lock(self, resource_id: int, window_id: int) -> None:
        """Transaction-scoped advisory lock preventing concurrent overbooking
        (ADR-006). No-op on non-PostgreSQL dialects (SQLite test convenience)."""
        dialect = self.session.bind.dialect.name if self.session.bind is not None else "sqlite"
        if dialect == "postgresql":
            self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"{resource_id}:{window_id}"},
            )

    def _validate_time_change(
        self,
        *,
        resource_id: int,
        starts: dt.datetime,
        ends: dt.datetime,
        exclude_booking_id: int | None,
    ) -> AvailabilityWindow:
        """Shared validation for creation and time amendments (API_SPEC §5.2-5.4).

        Order matters for correctness under concurrency: the advisory lock is
        acquired BEFORE the capacity count, so parallel transactions cannot
        both observe an empty slot and overbook (ADR-006).
        """
        if ends <= starts:
            raise validation_error(DETAIL_END_AFTER_START)
        resource = self.repo.get_resource(resource_id)
        if resource is None:
            raise not_found("Resource not found.")
        window = self._match_window(resource_id, starts, ends)
        if window is None:
            raise validation_error(DETAIL_WINDOW_MISMATCH)
        self._ensure_date_available(resource_id, starts, window)
        self._advisory_lock(resource_id, window.id)
        count = self.repo.count_active_overlapping(
            resource_id, starts, ends, exclude_id=exclude_booking_id
        )
        if count >= resource.capacity:
            raise conflict(DETAIL_SLOT_FULL)
        return window

    def _serialize_with_resource(self, booking: Booking) -> BookingWithResourceName:
        resource_name = booking.resource.name if booking.resource else "your booking"
        data = BookingRead.model_validate(booking).model_dump()
        return BookingWithResourceName(**data, resource_name=resource_name)

    # --- public: create ------------------------------------------------------

    def create(self, data: BookingCreate, *, base_url: str | None = None) -> BookingCreated:
        starts = parse_datetime(data.starts)
        ends = parse_datetime(data.ends)
        resource = self.repo.get_resource(data.resource_id)
        if resource is None:
            raise not_found("Resource not found.")

        # Everything below runs inside the request transaction; the advisory
        # lock (inside _validate_time_change) serialises concurrent creations
        # for the same resource/window before the capacity count (ADR-006).
        window = self._validate_time_change(
            resource_id=data.resource_id, starts=starts, ends=ends, exclude_booking_id=None
        )
        del window  # validation result; creation proceeds below

        raw_token = generate_token()
        booking = self.repo.create(
            resource_id=data.resource_id,
            email=str(data.email),
            name=data.name.strip(),
            notes=data.notes,
            starts=starts,
            ends=ends,
            cancelled=False,
            token_hash=hash_token(raw_token),
        )
        self.session.flush()

        # Persist the composed confirmation email in the outbox inside the
        # booking transaction (ADR-010, API_SPEC §8.2).
        website_base_url = (
            base_url
            or (
                self.settings.optimism_website_base_url
                if self.settings
                else "http://localhost:8000"
            )
        ).rstrip("/")
        cancellation_url = f"{website_base_url}/cancel-booking/{raw_token}"
        subject, body = compose_confirmation_email(
            name=booking.name,
            email=booking.email,
            notes=booking.notes,
            starts=booking.starts,
            ends=booking.ends,
            resource_name=resource.name,
            cancellation_url=cancellation_url,
        )
        self.outbox_repo.enqueue(
            booking_id=booking.id,
            subject=subject,
            body=body,
            from_addr=self.settings.optimism_email_org_from_addr
            if self.settings
            else "booking@example.org",
            to_addr=booking.email,
            bcc_addr=self.settings.optimism_email_org_notify_addr if self.settings else None,
        )
        self.session.flush()

        data_out = BookingRead.model_validate(booking).model_dump()
        return BookingCreated(**data_out, resource_name=resource.name, token=raw_token)

    # --- public: lookup / cancel / amend -------------------------------------

    def lookup_by_token(self, raw_token: str) -> BookingWithResourceName:
        booking = self.repo.get_by_token_hash(hash_token(raw_token))
        if booking is None:
            raise not_found(DETAIL_NO_BOOKING_WITH_TOKEN)
        return self._serialize_with_resource(booking)

    def cancel_by_token(self, raw_token: str) -> BookingCancelResponse:
        booking = self.repo.get_by_token_hash(hash_token(raw_token))
        if booking is None:
            raise not_found(DETAIL_NO_BOOKING_WITH_TOKEN)
        if booking.cancelled:
            # Idempotent (improvement #9): repeat cancels succeed with 200.
            return BookingCancelResponse(
                message="Booking cancelled successfully.",
                booking=self._serialize_with_resource(booking),
            )
        self._enforce_cutoff(booking, now=utcnow())
        self.repo.update(booking, cancelled=True)
        self.session.flush()
        return BookingCancelResponse(
            message="Booking cancelled successfully.",
            booking=self._serialize_with_resource(booking),
        )

    def amend_by_token(self, raw_token: str, data: BookingAmend) -> BookingWithResourceName:
        booking = self.repo.get_by_token_hash(hash_token(raw_token))
        if booking is None:
            raise not_found(DETAIL_NO_BOOKING_WITH_TOKEN)
        if booking.cancelled:
            raise conflict(DETAIL_CANCELLED_AMEND)
        self._enforce_cutoff(booking, now=utcnow())
        self._apply_amend(booking, data)
        self.session.flush()
        return self._serialize_with_resource(booking)

    # --- admin: list / get / amend / cancel / soft delete ---------------------

    def list_admin(self, filters: BookingListFilter) -> tuple[list[BookingWithResourceName], int]:
        from app.core.time import parse_datetime as _parse

        starts_from = _parse(filters.starts_from) if filters.starts_from else None
        starts_to = _parse(filters.starts_to) if filters.starts_to else None
        bookings, total = self.repo.list_filtered(
            resource_id=filters.resource_id,
            cancelled=filters.cancelled,
            email=filters.email,
            starts_from=starts_from,
            starts_to=starts_to,
            limit=filters.limit,
            offset=filters.offset,
        )
        return [self._serialize_with_resource(b) for b in bookings], total

    def get_admin(self, booking_id: int) -> BookingWithResourceName:
        booking = self.repo.get(booking_id)
        if booking is None:
            raise not_found("No such booking")
        return self._serialize_with_resource(booking)

    def amend_admin(self, booking_id: int, data: AdminBookingUpdate) -> BookingWithResourceName:
        booking = self.repo.get(booking_id)
        if booking is None:
            raise not_found("No such booking")
        # Admin amend is exempt from the cutoff (API_SPEC §1.8); time changes
        # are still revalidated against windows and capacity.
        self._apply_amend(booking, data)
        self.session.flush()
        return self._serialize_with_resource(booking)

    def cancel_admin(self, booking_id: int) -> BookingCancelResponse:
        booking = self.repo.get(booking_id)
        if booking is None:
            raise not_found("No such booking")
        if not booking.cancelled:
            self.repo.update(booking, cancelled=True)
            self.session.flush()
        return BookingCancelResponse(
            message="Booking cancelled successfully.",
            booking=self._serialize_with_resource(booking),
        )

    def soft_delete(self, booking_id: int) -> None:
        booking = self.repo.get(booking_id)
        if booking is None:
            raise not_found("No such booking")
        if booking.deleted_at is None:
            self.repo.update(booking, cancelled=True, deleted_at=utcnow())
            self.session.flush()

    # --- internals -----------------------------------------------------------

    def _enforce_cutoff(self, booking: Booking, *, now: dt.datetime) -> None:
        cutoff_minutes = self.settings.booking_cancellation_cutoff_minutes if self.settings else 5
        starts = ensure_utc(booking.starts) or utcnow()
        cutoff = starts - dt.timedelta(minutes=cutoff_minutes)
        if now >= cutoff:
            raise conflict(DETAIL_CUTOFF_PASSED)

    def _apply_amend(self, booking: Booking, data: BookingAmend) -> None:
        fields = data.model_dump(exclude_unset=True)
        if "starts" in fields or "ends" in fields:
            starts = parse_datetime(str(fields["starts"]))
            ends = parse_datetime(str(fields["ends"]))
            if ends <= starts:
                raise validation_error(DETAIL_END_AFTER_START)
            resource = self.repo.get_resource(booking.resource_id)
            if resource is None:
                raise not_found("Resource not found.")
            window = self._match_window(booking.resource_id, starts, ends)
            if window is None:
                raise validation_error(DETAIL_WINDOW_MISMATCH)
            self._ensure_date_available(booking.resource_id, starts, window)
            self._advisory_lock(booking.resource_id, window.id)
            count = self.repo.count_active_overlapping(
                booking.resource_id, starts, ends, exclude_id=booking.id
            )
            if count >= resource.capacity:
                raise conflict(DETAIL_SLOT_FULL)
            fields["starts"] = starts
            fields["ends"] = ends
        if "email" in fields:
            fields["email"] = str(fields["email"])
        if "name" in fields:
            fields["name"] = str(fields["name"]).strip()
        if fields:
            self.repo.update(booking, **fields)

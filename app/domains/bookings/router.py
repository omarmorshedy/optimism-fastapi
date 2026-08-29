"""API router for bookings (API_SPEC §3.4-3.7 public; §4.5 admin).

Route order matters: the token routes (lookup/amend/cancel) are registered
before ``/{booking_id}`` so ``lookup`` is never parsed as an id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from app.api.deps import limit_booking_cancel, limit_booking_create
from app.core.config import Settings
from app.core.metrics import BOOKING_CANCELLED, BOOKING_CREATED
from app.core.route import CommitOnSuccessRoute
from app.db.session import SessionDep
from app.domains.admin.audit import record_audit
from app.domains.admin.auth import require_admin, require_csrf
from app.domains.bookings.schemas import (
    AdminBookingUpdate,
    BookingAmend,
    BookingCancelResponse,
    BookingCreate,
    BookingCreated,
    BookingListFilter,
    BookingWithResourceName,
)
from app.domains.bookings.service import BookingService, resolve_public_base_url

bookings_router = APIRouter(prefix="/bookings", tags=["bookings"], route_class=CommitOnSuccessRoute)

BookingId = Annotated[int, Path(ge=0)]


def _service(session: SessionDep, request: Request) -> BookingService:
    settings: Settings = request.app.state.settings
    return BookingService(session, settings)


# --- admin list (never public — improvement #1) ------------------------------


@bookings_router.get("", response_model=list[BookingWithResourceName], dependencies=[require_admin])
def list_bookings(
    request: Request,
    session: SessionDep,
    filters: Annotated[BookingListFilter, Query()],
) -> list[BookingWithResourceName]:
    bookings, total = _service(session, request).list_admin(filters)
    request.state.total_count = total
    return bookings


# --- public create -----------------------------------------------------------


@bookings_router.post(
    "",
    response_model=BookingCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_booking_create)],
)
def create_booking(payload: BookingCreate, request: Request, session: SessionDep) -> BookingCreated:
    settings: Settings = request.app.state.settings
    email_base_url = resolve_public_base_url(
        settings.optimism_website_base_url, str(request.base_url).rstrip("/")
    )
    try:
        booking = _service(session, request).create(payload, base_url=email_base_url)
    except Exception:
        BOOKING_CREATED.labels(resource_id=str(payload.resource_id), status="error").inc()
        raise
    BOOKING_CREATED.labels(resource_id=str(payload.resource_id), status="success").inc()
    return booking


# --- public token routes (registered before /{booking_id}) -------------------


@bookings_router.get(
    "/lookup/{token}",
    response_model=BookingWithResourceName,
    dependencies=[Depends(limit_booking_cancel)],
)
def lookup_booking(token: str, request: Request, session: SessionDep) -> BookingWithResourceName:
    return _service(session, request).lookup_by_token(token)


@bookings_router.put(
    "/amend/{token}",
    response_model=BookingWithResourceName,
    dependencies=[Depends(limit_booking_cancel)],
)
def amend_booking(
    payload: BookingAmend, token: str, request: Request, session: SessionDep
) -> BookingWithResourceName:
    return _service(session, request).amend_by_token(token, payload)


@bookings_router.post(
    "/cancel/{token}",
    response_model=BookingCancelResponse,
    dependencies=[Depends(limit_booking_cancel)],
)
def cancel_booking(token: str, request: Request, session: SessionDep) -> BookingCancelResponse:
    response = _service(session, request).cancel_by_token(token)
    if response.booking.cancelled:
        BOOKING_CANCELLED.labels(resource_id=str(response.booking.resource_id)).inc()
    return response


# --- admin booking operations ------------------------------------------------


@bookings_router.get(
    "/{booking_id}", response_model=BookingWithResourceName, dependencies=[require_admin]
)
def get_booking(
    request: Request, session: SessionDep, booking_id: BookingId
) -> BookingWithResourceName:
    return _service(session, request).get_admin(booking_id)


@bookings_router.put(
    "/{booking_id}",
    response_model=BookingWithResourceName,
    dependencies=[require_admin, require_csrf],
)
def admin_update_booking(
    payload: AdminBookingUpdate,
    request: Request,
    session: SessionDep,
    booking_id: BookingId,
) -> BookingWithResourceName:
    obj = _service(session, request).amend_admin(booking_id, payload)
    record_audit(session, "booking.update", booking_id=booking_id)
    return obj


@bookings_router.post(
    "/{booking_id}/cancel",
    response_model=BookingCancelResponse,
    dependencies=[require_admin, require_csrf],
)
def admin_cancel_booking(
    request: Request, session: SessionDep, booking_id: BookingId
) -> BookingCancelResponse:
    response = _service(session, request).cancel_admin(booking_id)
    record_audit(session, "booking.cancel", booking_id=booking_id)
    return response


@bookings_router.delete(
    "/{booking_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def admin_delete_booking(request: Request, session: SessionDep, booking_id: BookingId) -> Response:
    _service(session, request).soft_delete(booking_id)
    record_audit(session, "booking.delete", booking_id=booking_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

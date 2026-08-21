"""API router for availability windows and exceptions (API_SPEC §4.4).

These list endpoints are admin-only; the public availability read is the
calendar endpoint (§4.4 note).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.core.route import CommitOnSuccessRoute
from app.db.session import SessionDep
from app.domains.admin.audit import record_audit
from app.domains.admin.auth import require_admin, require_csrf
from app.domains.windows.schemas import (
    AvailabilityExceptionCreate,
    AvailabilityExceptionRead,
    AvailabilityExceptionUpdate,
    AvailabilityWindowCreate,
    AvailabilityWindowRead,
    AvailabilityWindowUpdate,
)
from app.domains.windows.service import (
    AvailabilityExceptionService,
    AvailabilityWindowService,
)

windows_router = APIRouter(
    prefix="/availability-windows", tags=["availability-windows"], route_class=CommitOnSuccessRoute
)
exceptions_router = APIRouter(
    prefix="/availability-exceptions",
    tags=["availability-exceptions"],
    route_class=CommitOnSuccessRoute,
)

WindowId = Annotated[int, Path(ge=0)]
ExceptionId = Annotated[int, Path(ge=0)]


# --- availability windows ----------------------------------------------------


@windows_router.get("", response_model=list[AvailabilityWindowRead], dependencies=[require_admin])
def list_windows(
    session: SessionDep, resource_id: int | None = Query(default=None, ge=0, alias="resourceId")
) -> list[AvailabilityWindowRead]:
    return AvailabilityWindowService(session).list_all(resource_id)


@windows_router.post(
    "",
    response_model=AvailabilityWindowRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_admin, require_csrf],
)
def create_window(payload: AvailabilityWindowCreate, session: SessionDep) -> AvailabilityWindowRead:
    obj = AvailabilityWindowService(session).create(payload)
    record_audit(session, "availability_window.create", resource_id=obj.resource_id)
    return obj


@windows_router.get(
    "/{window_id}", response_model=AvailabilityWindowRead, dependencies=[require_admin]
)
def get_window(session: SessionDep, window_id: WindowId) -> AvailabilityWindowRead:
    return AvailabilityWindowService(session).get(window_id)


@windows_router.put(
    "/{window_id}",
    response_model=AvailabilityWindowRead,
    dependencies=[require_admin, require_csrf],
)
def update_window(
    payload: AvailabilityWindowUpdate, session: SessionDep, window_id: WindowId
) -> AvailabilityWindowRead:
    obj = AvailabilityWindowService(session).update(window_id, payload)
    record_audit(session, "availability_window.update", resource_id=obj.resource_id)
    return obj


@windows_router.delete(
    "/{window_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def delete_window(session: SessionDep, window_id: WindowId) -> Response:
    AvailabilityWindowService(session).delete(window_id)
    record_audit(session, "availability_window.delete", resource_id=window_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- availability exceptions -------------------------------------------------


@exceptions_router.get(
    "", response_model=list[AvailabilityExceptionRead], dependencies=[require_admin]
)
def list_exceptions(
    session: SessionDep, resource_id: int | None = Query(default=None, ge=0, alias="resourceId")
) -> list[AvailabilityExceptionRead]:
    return AvailabilityExceptionService(session).list_all(resource_id)


@exceptions_router.post(
    "",
    response_model=AvailabilityExceptionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_admin, require_csrf],
)
def create_exception(
    payload: AvailabilityExceptionCreate, session: SessionDep
) -> AvailabilityExceptionRead:
    obj = AvailabilityExceptionService(session).create(payload)
    record_audit(session, "availability_exception.create", resource_id=obj.resource_id)
    return obj


@exceptions_router.get(
    "/{exception_id}",
    response_model=AvailabilityExceptionRead,
    dependencies=[require_admin],
)
def get_exception(session: SessionDep, exception_id: ExceptionId) -> AvailabilityExceptionRead:
    return AvailabilityExceptionService(session).get(exception_id)


@exceptions_router.put(
    "/{exception_id}",
    response_model=AvailabilityExceptionRead,
    dependencies=[require_admin, require_csrf],
)
def update_exception(
    payload: AvailabilityExceptionUpdate, session: SessionDep, exception_id: ExceptionId
) -> AvailabilityExceptionRead:
    obj = AvailabilityExceptionService(session).update(exception_id, payload)
    record_audit(session, "availability_exception.update", resource_id=obj.resource_id)
    return obj


@exceptions_router.delete(
    "/{exception_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def delete_exception(session: SessionDep, exception_id: ExceptionId) -> Response:
    AvailabilityExceptionService(session).delete(exception_id)
    record_audit(session, "availability_exception.delete", resource_id=exception_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

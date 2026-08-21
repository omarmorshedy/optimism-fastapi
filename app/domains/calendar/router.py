"""API router for the calendar availability endpoint (API_SPEC §3.3, §6)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from app.api.deps import limit_calendar_read
from app.core.route import CommitOnSuccessRoute
from app.core.time import parse_date
from app.db.session import SessionDep
from app.domains.calendar.service import CalendarService

calendar_router = APIRouter(prefix="/calendar", tags=["calendar"], route_class=CommitOnSuccessRoute)

ResourceId = Annotated[int, Path(ge=0)]


@calendar_router.get(
    "/{start_date}/{end_date}/{resource_id}",
    dependencies=[Depends(limit_calendar_read)],
)
def get_calendar(
    session: SessionDep,
    start_date: str,
    end_date: str,
    resource_id: ResourceId,
) -> dict[str, Any]:
    # parse_date raises TimeError → 422 problem for malformed dates (spec §1.2).
    parsed_start = parse_date(start_date)
    parsed_end = parse_date(end_date)
    return CalendarService(session).get(parsed_start, parsed_end, resource_id)

"""Web routes: public booking flow + admin UI (Jinja templates).

Public pages: /, /select-a-resource, /select-a-time, POST /your-details,
POST /confirmation, GET/POST /cancel-booking/{token}.
Admin pages: /admin/* (login, dashboard, resource types, resources, windows,
exceptions, bookings).

The web layer calls the same-process domain services; the API contract still
governs all business rules.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.config import Settings
from app.core.exceptions import Problem
from app.core.time import format_llll, parse_datetime
from app.db.session import SessionDep
from app.domains.admin.audit import record_audit
from app.domains.admin.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AdminAuthService,
)
from app.domains.bookings.schemas import BookingCreate
from app.domains.bookings.service import BookingService
from app.domains.calendar.service import CalendarService
from app.domains.resources.schemas import (
    ResourceCreate,
    ResourceTypeCreate,
    ResourceTypeUpdate,
    ResourceUpdate,
)
from app.domains.resources.service import ResourceService, ResourceTypeService
from app.domains.windows.schemas import (
    AvailabilityExceptionCreate,
    AvailabilityWindowCreate,
    AvailabilityWindowUpdate,
    WindowReplacementItem,
)
from app.domains.windows.service import (
    AvailabilityExceptionService,
    AvailabilityWindowService,
)
from app.web.deps import (
    INTENT_COOKIE,
    UserIntent,
    load_intent,
    sign_intent,
    verify_form_csrf,
)

web_router = APIRouter(include_in_schema=False)

TEMPLATE_DIRS = {
    "modern": Path(__file__).parent / "templates",
    "legacy": Path(__file__).parent / "templates_legacy",
}
_templates = {
    name: Jinja2Templates(directory=str(directory)) for name, directory in TEMPLATE_DIRS.items()
}


def render(request: Request, name: str, **context: object) -> HTMLResponse:
    """Render a template from the configured UI theme (Settings.web_theme)."""
    theme = _settings(request).web_theme
    context.setdefault("request", request)
    return _templates[theme].TemplateResponse(request=request, name=name, context=context)


def _settings(request: Request) -> Settings:
    settings = request.app.state.settings
    return settings  # type: ignore[no-any-return]


def _csrf(request: Request) -> str:
    return request.cookies.get(CSRF_COOKIE, "")


def _error(request: Request, message: str, status: int = 400) -> HTMLResponse:
    response = render(request, "error.html", safeErrorMessage=message)
    response.status_code = status
    return response


def _require_admin_page(request: Request, session: SessionDep) -> str:
    """Redirect to the login page when there is no valid admin session."""
    settings = _settings(request)
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        auth = AdminAuthService(session, settings)
        if auth.get_session(raw) is not None:
            return raw
    raise HTTPException(
        status_code=303,
        headers={"location": f"/admin/login?redirect={request.url.path}"},
    )


def _admin_context(request: Request) -> dict[str, object]:
    return {"csrf_token": _csrf(request)}


def _friendly(booking: dict[str, object], resource_name: str) -> dict[str, object]:
    starts = str(booking["starts"])
    ends = str(booking["ends"])
    return {
        "booking": booking,
        "resourceName": resource_name,
        "friendlyStartTime": format_llll(parse_datetime(starts)),
        "friendlyEndTime": format_llll(parse_datetime(ends)),
    }


# --- public: home ------------------------------------------------------------


@web_router.get("/")
def home(request: Request) -> HTMLResponse:
    return render(request, "home.html")


# --- public: choose resource -------------------------------------------------


@web_router.get("/select-a-resource")
def select_a_resource(request: Request, session: SessionDep) -> HTMLResponse:
    try:
        resources = [r.model_dump(by_alias=True) for r in ResourceService(session).list()]
        types = ResourceTypeService(session).list()
    except Problem as exc:
        return _error(request, exc.detail)
    type_names = {t.id: t.name for t in types}
    for r in resources:
        r["resourceTypeName"] = type_names.get(r["resourceTypeId"])
    return render(request, "select-a-resource.html", resources=resources)


# --- public: choose time -----------------------------------------------------


@web_router.get("/select-a-time")
def select_a_time(
    request: Request, session: SessionDep, resource: int | None = None
) -> HTMLResponse:
    settings = _settings(request)
    if resource is None:
        return _error(request, "No resource was selected.")
    try:
        resource_obj = ResourceService(session).get(resource).model_dump(by_alias=True)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    # Initial week (today .. +6 days) is rendered server-side so the page works
    # without JavaScript; the calendar JS fetches further weeks via /calendar-data.
    from app.core.time import utcnow as _utcnow

    today = _utcnow().date()
    initial_calendar = CalendarService(session).get(today, today + dt.timedelta(days=6), resource)
    intent = UserIntent(resource_id=resource)
    response = render(
        request,
        "select-a-time.html",
        resource=resource_obj,
        resource_id=resource,
        initial_start=today.isoformat(),
        initial_end=(today + dt.timedelta(days=6)).isoformat(),
        initial_calendar=initial_calendar,
        csrf_token=_csrf(request),
    )
    response.set_cookie(
        key=INTENT_COOKIE,
        value=sign_intent(settings, intent),
        max_age=2 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@web_router.get("/calendar-data")
def calendar_data_web(
    request: Request,
    session: SessionDep,
    start: str,
    end: str,
    resource: int,
) -> dict[str, object]:
    """Same-process calendar JSON for the select-a-time page's JS (public)."""
    try:
        from app.core.time import parse_date

        return CalendarService(session).get(parse_date(start), parse_date(end), resource)
    except Problem as exc:
        return {"dates": [], "error": exc.detail}


# --- public: details ---------------------------------------------------------


@web_router.post("/your-details")
def your_details(
    request: Request,
    session: SessionDep,
    resource: int = Form(...),
    slot: str = Form(...),
) -> HTMLResponse:
    settings = _settings(request)
    intent = load_intent(settings, request.cookies.get(INTENT_COOKIE))
    if intent is None or intent.resource_id != resource:
        return _error(request, "Your session has expired. Please start again.", status=400)
    parts = slot.split("|")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return _error(request, "Please select a time slot.")
    start, finish = parts[0], parts[1]
    intent.starts = start
    intent.ends = finish
    try:
        resource_obj = ResourceService(session).get(resource).model_dump(by_alias=True)
    except Problem as exc:
        return _error(request, exc.detail, status=404)
    response = render(
        request,
        "your-details.html",
        resource=resource_obj,
        startTime=start,
        endTime=finish,
        friendlyStartTime=format_llll(parse_datetime(start)),
        friendlyEndTime=format_llll(parse_datetime(finish)),
        csrf_token=_csrf(request),
    )
    response.set_cookie(
        key=INTENT_COOKIE,
        value=sign_intent(settings, intent),
        max_age=2 * 3600,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


# --- public: confirmation ----------------------------------------------------


@web_router.post("/confirmation")
def confirmation(
    request: Request,
    session: SessionDep,
    resourceId: int = Form(...),
    name: str = Form(...),
    email: str = Form(...),
    starts: str = Form(...),
    ends: str = Form(...),
    notes: str = Form(""),
) -> HTMLResponse:
    settings = _settings(request)
    service = BookingService(session, settings)
    try:
        created = service.create(
            BookingCreate(
                resource_id=resourceId,
                name=name,
                email=email,
                starts=starts,
                ends=ends,
                notes=notes,
            )
        )
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    booking = created.model_dump(by_alias=True)
    cancellation_url = f"{settings.optimism_website_base_url}/cancel-booking/{booking['token']}"
    return render(
        request,
        "confirmation.html",
        **_friendly(booking, booking["resourceName"]),
        raw_token=booking["token"],
        cancellation_url=cancellation_url,
    )


# --- public: cancellation ----------------------------------------------------


@web_router.get("/cancel-booking/{token}")
def cancel_booking_page(request: Request, session: SessionDep, token: str) -> HTMLResponse:
    """GET renders a confirmation page; the POST below performs the change
    (fixes the legacy GET-cancels hazard; API_SPEC §7)."""
    settings = _settings(request)
    service = BookingService(session, settings)
    try:
        booking = service.lookup_by_token(token).model_dump(by_alias=True)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return render(
        request,
        "cancel-booking.html",
        booking=booking,
        token=token,
        friendlyStartTime=format_llll(parse_datetime(booking["starts"])),
        friendlyEndTime=format_llll(parse_datetime(booking["ends"])),
        already_cancelled=booking["cancelled"],
        csrf_token=_csrf(request),
    )


@web_router.post("/cancel-booking/{token}")
def cancel_booking_action(request: Request, session: SessionDep, token: str) -> HTMLResponse:
    settings = _settings(request)
    service = BookingService(session, settings)
    try:
        result = service.cancel_by_token(token)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    booking = result.booking.model_dump(by_alias=True)
    return render(
        request,
        "cancel-booking.html",
        booking=booking,
        token=token,
        friendlyStartTime=format_llll(parse_datetime(booking["starts"])),
        friendlyEndTime=format_llll(parse_datetime(booking["ends"])),
        success=True,
        message=result.message,
        already_cancelled=booking["cancelled"],
        csrf_token=_csrf(request),
    )


# --- admin: auth -------------------------------------------------------------


@web_router.get("/admin/login")
def admin_login_page(request: Request, redirect: str | None = None) -> HTMLResponse:
    return render(request, "admin/login.html", redirect=redirect or "/admin/")


@web_router.post("/admin/login")
def admin_login_post(
    request: Request,
    session: SessionDep,
    password: str = Form(...),
    redirect: str = Form("/admin/"),
) -> Response:
    settings = _settings(request)
    auth = AdminAuthService(session, settings)
    try:
        raw_token, csrf_token, _expires = auth.login(password)
    except Problem:
        return render(request, "admin/login.html", error="Invalid credentials.", redirect=redirect)
    if not redirect.startswith("/"):
        redirect = "/admin/"
    response = RedirectResponse(redirect, status_code=303)
    max_age = settings.session_max_age_seconds
    secure = settings.environment == "production"
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,
        samesite="lax",
    )
    return response


@web_router.post("/admin/logout")
def admin_logout_post(
    request: Request,
    session: SessionDep,
    csrf_token: str = Form(""),
) -> Response:
    verify_form_csrf(request, csrf_token)
    settings = _settings(request)
    raw = request.cookies.get(SESSION_COOKIE)
    if raw:
        AdminAuthService(session, settings).logout(raw)
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response


# --- admin: dashboard --------------------------------------------------------


@web_router.get("/admin")
def admin_dashboard(request: Request, session: SessionDep) -> HTMLResponse:
    _require_admin_page(request, session)
    return render(request, "admin/dashboard.html", **_admin_context(request))


# --- admin: resource types ---------------------------------------------------


@web_router.get("/admin/resource-types")
def admin_resource_types(request: Request, session: SessionDep) -> HTMLResponse:
    _require_admin_page(request, session)
    items = [i.model_dump(by_alias=True) for i in ResourceTypeService(session).list()]
    return render(request, "admin/resource-types.html", items=items, **_admin_context(request))


@web_router.post("/admin/resource-types/create")
def admin_resource_type_create(
    request: Request,
    session: SessionDep,
    name: str = Form(...),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = ResourceTypeService(session).create(ResourceTypeCreate(name=name))
        record_audit(session, "resource_type.create", resource_id=obj.id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resource-types", status_code=303)


@web_router.get("/admin/resource-types/{type_id}/edit")
def admin_resource_type_edit_page(
    request: Request, session: SessionDep, type_id: int
) -> HTMLResponse:
    _require_admin_page(request, session)
    item = ResourceTypeService(session).get(type_id).model_dump(by_alias=True)
    return render(request, "admin/resource-type-edit.html", item=item, **_admin_context(request))


@web_router.post("/admin/resource-types/{type_id}/edit")
def admin_resource_type_edit(
    request: Request,
    session: SessionDep,
    type_id: int,
    name: str = Form(...),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = ResourceTypeService(session).update(type_id, ResourceTypeUpdate(name=name))
        record_audit(session, "resource_type.update", resource_id=obj.id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resource-types", status_code=303)


@web_router.post("/admin/resource-types/{type_id}/delete")
def admin_resource_type_delete(
    request: Request,
    session: SessionDep,
    type_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        ResourceTypeService(session).delete(type_id)
        record_audit(session, "resource_type.delete", resource_id=type_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resource-types", status_code=303)


# --- admin: resources --------------------------------------------------------


@web_router.get("/admin/resources")
def admin_resources(request: Request, session: SessionDep) -> HTMLResponse:
    _require_admin_page(request, session)
    items = [r.model_dump(by_alias=True) for r in ResourceService(session).list()]
    types = {t.id: t.name for t in ResourceTypeService(session).list()}
    for r in items:
        r["resourceTypeName"] = types.get(r["resourceTypeId"])
    return render(
        request, "admin/resources.html", items=items, types=types, **_admin_context(request)
    )


@web_router.post("/admin/resources/create")
def admin_resource_create(
    request: Request,
    session: SessionDep,
    name: str = Form(...),
    capacity: int = Form(...),
    resourceTypeId: str = Form(""),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = ResourceService(session).create(
            ResourceCreate(
                name=name,
                capacity=capacity,
                resource_type_id=int(resourceTypeId) if resourceTypeId.strip() else None,
            )
        )
        record_audit(session, "resource.create", resource_id=obj.id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resources", status_code=303)


@web_router.get("/admin/resources/{resource_id}/edit")
def admin_resource_edit_page(
    request: Request, session: SessionDep, resource_id: int
) -> HTMLResponse:
    _require_admin_page(request, session)
    item = ResourceService(session).get(resource_id).model_dump(by_alias=True)
    types = [t.model_dump(by_alias=True) for t in ResourceTypeService(session).list()]
    return render(
        request, "admin/resource-edit.html", item=item, types=types, **_admin_context(request)
    )


@web_router.post("/admin/resources/{resource_id}/edit")
def admin_resource_edit(
    request: Request,
    session: SessionDep,
    resource_id: int,
    name: str = Form(...),
    capacity: int = Form(...),
    resourceTypeId: str = Form(""),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = ResourceService(session).update(
            resource_id,
            ResourceUpdate(
                name=name,
                capacity=capacity,
                resource_type_id=int(resourceTypeId) if resourceTypeId.strip() else None,
            ),
        )
        record_audit(session, "resource.update", resource_id=obj.id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resources", status_code=303)


@web_router.post("/admin/resources/{resource_id}/delete")
def admin_resource_delete(
    request: Request,
    session: SessionDep,
    resource_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        ResourceService(session).delete(resource_id)
        record_audit(session, "resource.delete", resource_id=resource_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/resources", status_code=303)


# --- admin: windows (per resource + global) ----------------------------------


@web_router.get("/admin/resources/{resource_id}/windows")
def admin_resource_windows_page(
    request: Request, session: SessionDep, resource_id: int
) -> HTMLResponse:
    _require_admin_page(request, session)
    resource = ResourceService(session).get(resource_id).model_dump(by_alias=True)
    windows = [
        w.model_dump(by_alias=True)
        for w in AvailabilityWindowService(session).list_for_resource(resource_id)
    ]
    return render(
        request,
        "admin/resource-windows.html",
        resource=resource,
        windows=windows,
        **_admin_context(request),
    )


@web_router.post("/admin/resources/{resource_id}/windows")
async def admin_resource_windows_replace(
    request: Request,
    session: SessionDep,
    resource_id: int,
) -> Response:
    """Replaces all windows for a resource from repeated form rows."""
    _require_admin_page(request, session)
    form = await request.form()
    verify_form_csrf(request, str(form.get("csrf_token", "")))
    items: list[WindowReplacementItem] = []
    weekdays = form.getlist("weekday")
    starts = form.getlist("starts")
    ends = form.getlist("ends")
    names = form.getlist("name")
    for i, weekday in enumerate(weekdays):
        if not str(weekday).strip() and not str(starts[i]).strip():
            continue
        items.append(
            WindowReplacementItem(
                weekday=int(str(weekday)),
                starts=str(starts[i]),
                ends=str(ends[i]),
                name=str(names[i]).strip() or None,
            )
        )
    try:
        AvailabilityWindowService(session).replace_for_resource(resource_id, items)
        record_audit(session, "resource.windows.replace", resource_id=resource_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse(f"/admin/resources/{resource_id}/windows", status_code=303)


@web_router.get("/admin/windows")
def admin_windows(request: Request, session: SessionDep) -> HTMLResponse:
    _require_admin_page(request, session)
    items = [w.model_dump(by_alias=True) for w in AvailabilityWindowService(session).list_all()]
    resources = {r.id: r.name for r in ResourceService(session).list()}
    return render(
        request, "admin/windows.html", items=items, resources=resources, **_admin_context(request)
    )


@web_router.post("/admin/windows/create")
def admin_window_create(
    request: Request,
    session: SessionDep,
    resourceId: int = Form(...),
    weekday: int = Form(...),
    starts: str = Form(...),
    ends: str = Form(...),
    name: str = Form(""),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = AvailabilityWindowService(session).create(
            AvailabilityWindowCreate(
                resource_id=resourceId,
                weekday=weekday,
                starts=starts,
                ends=ends,
                name=name.strip() or None,
            )
        )
        record_audit(session, "availability_window.create", resource_id=obj.resource_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/windows", status_code=303)


@web_router.get("/admin/windows/{window_id}/edit")
def admin_window_edit_page(request: Request, session: SessionDep, window_id: int) -> HTMLResponse:
    _require_admin_page(request, session)
    item = AvailabilityWindowService(session).get(window_id).model_dump(by_alias=True)
    resources = [r.model_dump(by_alias=True) for r in ResourceService(session).list()]
    return render(
        request, "admin/window-edit.html", item=item, resources=resources, **_admin_context(request)
    )


@web_router.post("/admin/windows/{window_id}/edit")
def admin_window_edit(
    request: Request,
    session: SessionDep,
    window_id: int,
    resourceId: int = Form(...),
    weekday: int = Form(...),
    starts: str = Form(...),
    ends: str = Form(...),
    name: str = Form(""),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        obj = AvailabilityWindowService(session).update(
            window_id,
            AvailabilityWindowUpdate(
                resource_id=resourceId,
                weekday=weekday,
                starts=starts,
                ends=ends,
                name=name.strip() or None,
            ),
        )
        record_audit(session, "availability_window.update", resource_id=obj.resource_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/windows", status_code=303)


@web_router.post("/admin/windows/{window_id}/delete")
def admin_window_delete(
    request: Request,
    session: SessionDep,
    window_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        AvailabilityWindowService(session).delete(window_id)
        record_audit(session, "availability_window.delete", resource_id=window_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/windows", status_code=303)


# --- admin: exceptions -------------------------------------------------------


@web_router.get("/admin/exceptions")
def admin_exceptions(request: Request, session: SessionDep) -> HTMLResponse:
    _require_admin_page(request, session)
    items = [e.model_dump(by_alias=True) for e in AvailabilityExceptionService(session).list_all()]
    resources = {r.id: r.name for r in ResourceService(session).list()}
    return render(
        request,
        "admin/exceptions.html",
        items=items,
        resources=resources,
        **_admin_context(request),
    )


@web_router.post("/admin/exceptions/create")
def admin_exception_create(
    request: Request,
    session: SessionDep,
    resourceId: int = Form(...),
    startDate: str = Form(...),
    endDate: str = Form(...),
    kind: str = Form(...),
    reason: str = Form(""),
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        from app.core.time import parse_date

        obj = AvailabilityExceptionService(session).create(
            AvailabilityExceptionCreate(
                resource_id=resourceId,
                start_date=parse_date(startDate),
                end_date=parse_date(endDate),
                kind=kind,
                reason=reason.strip() or None,
            )
        )
        record_audit(session, "availability_exception.create", resource_id=obj.resource_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/exceptions", status_code=303)


@web_router.post("/admin/exceptions/{exception_id}/delete")
def admin_exception_delete(
    request: Request,
    session: SessionDep,
    exception_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    try:
        AvailabilityExceptionService(session).delete(exception_id)
        record_audit(session, "availability_exception.delete", resource_id=exception_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/exceptions", status_code=303)


# --- admin: bookings ---------------------------------------------------------


@web_router.get("/admin/bookings")
def admin_bookings(
    request: Request,
    session: SessionDep,
    resourceId: int | None = None,
    cancelled: str | None = None,
    email: str | None = None,
    startsFrom: str | None = None,
    startsTo: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> HTMLResponse:
    _require_admin_page(request, session)
    from app.domains.bookings.schemas import BookingListFilter

    settings = _settings(request)
    filters = BookingListFilter(
        resource_id=resourceId,
        cancelled={"true": True, "false": False}.get(cancelled or ""),
        email=email,
        starts_from=startsFrom,
        starts_to=startsTo,
        limit=limit,
        offset=offset,
    )
    booking_rows, _total = BookingService(session, settings).list_admin(filters)
    items = [b.model_dump(by_alias=True) for b in booking_rows]
    resources = {r.id: r.name for r in ResourceService(session).list()}
    return render(
        request, "admin/bookings.html", items=items, resources=resources, **_admin_context(request)
    )


@web_router.get("/admin/bookings/{booking_id}")
def admin_booking_detail(request: Request, session: SessionDep, booking_id: int) -> HTMLResponse:
    _require_admin_page(request, session)
    settings = _settings(request)
    booking = BookingService(session, settings).get_admin(booking_id).model_dump(by_alias=True)
    return render(
        request,
        "admin/booking-detail.html",
        booking=booking,
        friendlyStartTime=format_llll(parse_datetime(booking["starts"])),
        friendlyEndTime=format_llll(parse_datetime(booking["ends"])),
        **_admin_context(request),
    )


@web_router.post("/admin/bookings/{booking_id}/cancel")
def admin_booking_cancel(
    request: Request,
    session: SessionDep,
    booking_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    settings = _settings(request)
    try:
        BookingService(session, settings).cancel_admin(booking_id)
        record_audit(session, "booking.cancel", booking_id=booking_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse(f"/admin/bookings/{booking_id}", status_code=303)


@web_router.post("/admin/bookings/{booking_id}/delete")
def admin_booking_delete(
    request: Request,
    session: SessionDep,
    booking_id: int,
    csrf_token: str = Form(""),
) -> Response:
    _require_admin_page(request, session)
    verify_form_csrf(request, csrf_token)
    settings = _settings(request)
    try:
        BookingService(session, settings).soft_delete(booking_id)
        record_audit(session, "booking.delete", booking_id=booking_id)
    except Problem as exc:
        return _error(request, exc.detail, status=exc.status)
    return RedirectResponse("/admin/bookings", status_code=303)

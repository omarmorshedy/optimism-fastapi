"""RFC 7807 problem-details errors and global exception handlers (API_SPEC §1.3, §9)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.time import TimeError

logger = logging.getLogger("optimism.errors")

# Base URL for problem `type` URIs (API_SPEC §1.3 examples use https://optimism.example/errors/...).
PROBLEM_BASE_URL = "https://optimism.example/errors"
PROBLEM_MEDIA_TYPE = "application/problem+json"

# type-suffix -> (status, title) per the error catalog (API_SPEC §9).
PROBLEM_TYPES: dict[str, tuple[int, str]] = {
    "validation": (422, "Unprocessable Entity"),
    "not-found": (404, "Not Found"),
    "conflict": (409, "Conflict"),
    "unauthorized": (401, "Unauthorized"),
    "forbidden": (403, "Forbidden"),
    "rate-limited": (429, "Too Many Requests"),
    "unavailable": (503, "Service Unavailable"),
    "internal": (500, "Internal Server Error"),
}

# Detail strings preserved verbatim from the legacy API (API_SPEC §1.3).
DETAIL_RESOURCE_NOT_FOUND = "Resource not found."
DETAIL_NO_SUCH_RESOURCE = "No such resource."
DETAIL_NO_SUCH_BOOKING = "No such booking"
DETAIL_END_AFTER_START = "End time must be after start time."
DETAIL_SLOT_FULL = "This time slot is already fully booked. Please select another time."
DETAIL_NO_BOOKING_WITH_TOKEN = "No booking found with this token."
DETAIL_ALREADY_CANCELLED = "This booking has already been cancelled."
DETAIL_CUTOFF_PASSED = "This booking can no longer be changed or cancelled."
DETAIL_BOOKING_CANCELLED = "This booking has been cancelled and cannot be amended."


class Problem(Exception):
    """An RFC 7807 problem-details error raised by application code."""

    def __init__(
        self,
        type_suffix: str,
        detail: str,
        *,
        status: int | None = None,
        title: str | None = None,
        instance: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if type_suffix not in PROBLEM_TYPES:
            raise ValueError(f"Unknown problem type: {type_suffix}")
        default_status, default_title = PROBLEM_TYPES[type_suffix]
        self.type_suffix = type_suffix
        self.status = status if status is not None else default_status
        self.title = title if title is not None else default_title
        self.detail = detail
        self.instance = instance
        self.headers = headers
        super().__init__(detail)

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": f"{PROBLEM_BASE_URL}/{self.type_suffix}",
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
        }
        if self.instance:
            body["instance"] = self.instance
        if request_id:
            body["request_id"] = request_id
        return body


# --- Convenience constructors -------------------------------------------------


def validation_error(detail: str, instance: str | None = None) -> Problem:
    return Problem("validation", detail, instance=instance)


def not_found(detail: str, instance: str | None = None) -> Problem:
    return Problem("not-found", detail, instance=instance)


def conflict(detail: str, instance: str | None = None) -> Problem:
    return Problem("conflict", detail, instance=instance)


def unauthorized(detail: str = "Not authenticated.", instance: str | None = None) -> Problem:
    return Problem("unauthorized", detail, instance=instance)


def forbidden(detail: str = "Not authorised.", instance: str | None = None) -> Problem:
    return Problem("forbidden", detail, instance=instance)


def rate_limited(
    detail: str = "Too many requests. Please try again later.", instance: str | None = None
) -> Problem:
    return Problem("rate-limited", detail, instance=instance)


def unavailable(
    detail: str = "Service temporarily unavailable.", instance: str | None = None
) -> Problem:
    return Problem("unavailable", detail, instance=instance)


def internal_error(
    detail: str = "An unexpected error occurred.", instance: str | None = None
) -> Problem:
    return Problem("internal", detail, instance=instance)


# --- Handlers ----------------------------------------------------------------


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _problem_response(request: Request, problem: Problem) -> JSONResponse:
    return JSONResponse(
        status_code=problem.status,
        content=problem.to_dict(request_id=_request_id(request)),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(problem.headers or {}),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install global exception handlers mapping exceptions to RFC 7807 responses."""

    @app.exception_handler(Problem)
    async def problem_handler(request: Request, exc: Problem) -> JSONResponse:
        return _problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(
            str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path")
        )
        msg = first.get("msg", "Invalid request.")
        detail = f"Invalid input for '{loc}': {msg}" if loc else str(msg)
        return _problem_response(request, validation_error(detail, instance=str(request.url.path)))

    @app.exception_handler(ValidationError)
    async def pydantic_validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        errors = exc.errors(include_url=False)
        message = str(errors[0]["msg"]) if errors else "Invalid input."
        return _problem_response(
            request, validation_error(message, instance=str(request.url.path))
        )

    @app.exception_handler(TimeError)
    async def time_error_handler(request: Request, exc: TimeError) -> JSONResponse:
        return _problem_response(
            request, validation_error(str(exc), instance=str(request.url.path))
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse | Response:
        # Pass through redirects (used by the web admin guard).
        headers = dict(exc.headers or {})
        if exc.status_code in (301, 302, 303, 307, 308) and headers.get("location"):
            return Response(status_code=exc.status_code, headers=headers)
        # Map Starlette's generic HTTP exceptions into the problem catalog.
        if exc.status_code == 404:
            problem = not_found(str(exc.detail), instance=str(request.url.path))
        elif exc.status_code == 401:
            problem = unauthorized(str(exc.detail))
        elif exc.status_code == 403:
            problem = forbidden(str(exc.detail))
        elif exc.status_code == 429:
            problem = rate_limited(str(exc.detail))
        else:
            problem = Problem("internal", str(exc.detail), status=exc.status_code)
        return _problem_response(request, problem)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_error",
            extra={
                "request_id": _request_id(request),
                "path": str(request.url.path),
                "method": request.method,
            },
            exc_info=exc,
        )
        return _problem_response(request, internal_error(instance=str(request.url.path)))

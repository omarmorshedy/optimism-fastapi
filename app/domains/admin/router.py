"""API router for admin login/logout (API_SPEC §4.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import limit_admin_login
from app.core.config import Settings
from app.db.session import SessionDep
from app.domains.admin.auth import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    AdminAuthService,
    require_admin,
    require_csrf,
)
from app.domains.admin.schemas import LoginRequest, LoginResponse

admin_router = APIRouter(prefix="/admin", tags=["admin"])


def _set_auth_cookies(
    response: Response, raw_session_token: str, csrf_token: str, settings: Settings
) -> None:
    max_age = settings.session_max_age_seconds
    secure = settings.environment == "production"
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_session_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        key=CSRF_COOKIE,
        value=csrf_token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=False,  # double-submit: JS reads it to send X-CSRF-Token
        samesite="lax",
    )


@admin_router.post("/login", dependencies=[Depends(limit_admin_login)])
def login(payload: LoginRequest, request: Request, session: SessionDep) -> JSONResponse:
    settings: Settings = request.app.state.settings
    auth = AdminAuthService(session, settings)
    raw_token, csrf_token, _expires = auth.login(payload.password)
    body = LoginResponse().model_dump()
    response = JSONResponse(content=body, status_code=status.HTTP_200_OK)
    _set_auth_cookies(response, raw_token, csrf_token, settings)
    return response


@admin_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_admin, require_csrf],
)
def logout(request: Request, session: SessionDep) -> Response:
    raw_token = request.cookies.get(SESSION_COOKIE)
    settings: Settings = request.app.state.settings
    if raw_token:
        AdminAuthService(session, settings).logout(raw_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response

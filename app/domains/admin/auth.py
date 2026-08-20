"""Admin authentication and session handling (API_SPEC §1.4, §4.1; ADR-005).

One shared credential: the bcrypt hash lives in ``ADMIN_PASSWORD_HASH`` (secret
management). A successful login creates a server-side ``admin_sessions`` row and
sets a signed ``Secure; HttpOnly; SameSite=Lax`` cookie (1 h expiry, rotated on
login, revocable via logout). CSRF protection is double-submit cookie.
"""

from __future__ import annotations

import datetime as dt

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import forbidden, unauthorized
from app.core.security import constant_time_equals, generate_token, hash_token, verify_password
from app.core.time import ensure_utc, utcnow
from app.db.session import SessionDep, SettingsDep
from app.domains.admin.repository import AdminSessionRepository

SESSION_COOKIE = "optimism_admin_session"
CSRF_COOKIE = "csrf_token"

DETAIL_INVALID_CREDENTIALS = "Invalid credentials."
DETAIL_CSRF = "CSRF token missing or invalid."


class AdminAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = AdminSessionRepository(session)

    def login(self, password: str) -> tuple[str, str, dt.datetime]:
        """Verify the shared credential; on success create a session.

        Returns ``(raw_session_token, csrf_token, expires_at)``.
        """
        if not verify_password(password, self.settings.admin_password_hash):
            raise unauthorized(DETAIL_INVALID_CREDENTIALS)
        raw_token = generate_token()
        csrf_token = generate_token()
        expires_at = utcnow() + dt.timedelta(seconds=self.settings.session_max_age_seconds)
        self.repo.create(token_hash=hash_token(raw_token), expires_at=expires_at)
        self.session.flush()
        return raw_token, csrf_token, expires_at

    def get_session(self, raw_token: str) -> object | None:
        """Resolve a session cookie value to a valid, unexpired session."""
        obj = self.repo.get_by_token_hash(hash_token(raw_token))
        if obj is None:
            return None
        expires_at = ensure_utc(obj.expires_at)
        if expires_at is not None and expires_at <= utcnow():
            return None
        self.repo.touch(obj)
        return obj

    def logout(self, raw_token: str) -> None:
        obj = self.repo.get_by_token_hash(hash_token(raw_token))
        if obj is not None:
            self.repo.delete(obj)


def get_admin_auth_service(session: SessionDep, settings: SettingsDep) -> AdminAuthService:
    return AdminAuthService(session, settings)


def get_current_admin(request: Request, session: SessionDep, settings: SettingsDep) -> object:
    """FastAPI dependency: require a valid admin session (401 otherwise)."""
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise unauthorized()
    auth = AdminAuthService(session, settings)
    admin = auth.get_session(raw_token)
    if admin is None:
        raise unauthorized()
    return admin


require_admin = Depends(get_current_admin)


def verify_csrf(request: Request) -> None:
    """Double-submit cookie CSRF check for cookie-authenticated writes."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get("X-CSRF-Token")
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise forbidden(DETAIL_CSRF)


require_csrf = Depends(verify_csrf)

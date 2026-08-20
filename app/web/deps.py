"""Web-layer dependencies: admin page guard, form CSRF, signed user intent.

The web UI talks to the same-process domain services (ADR-001); no HTTP hop.
"""

from __future__ import annotations

from typing import cast

from fastapi import Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import Settings
from app.core.exceptions import forbidden
from app.core.security import constant_time_equals
from app.db.session import SessionDep
from app.domains.admin.auth import CSRF_COOKIE, AdminAuthService

INTENT_COOKIE = "user_intent"
INTENT_MAX_AGE_SECONDS = 2 * 3600


class UserIntent:
    def __init__(
        self, *, resource_id: int, starts: str | None = None, ends: str | None = None
    ) -> None:
        self.resource_id = resource_id
        self.starts = starts
        self.ends = ends


def get_optional_admin(
    request: Request, session: SessionDep, settings: Settings | None = None
) -> object | None:
    """Return the current admin session or None (no exception raised)."""
    raw_token = request.cookies.get("optimism_admin_session")
    if not raw_token:
        return None
    settings = settings or request.app.state.settings
    auth = AdminAuthService(session, settings)
    return auth.get_session(raw_token)


def verify_form_csrf(request: Request, csrf_field: str | None) -> None:
    """Double-submit cookie CSRF check for HTML form posts."""
    cookie = request.cookies.get(CSRF_COOKIE)
    if not cookie or not csrf_field or not constant_time_equals(cookie, csrf_field):
        raise forbidden("CSRF token missing or invalid.")


def get_intent_serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt="optimism-user-intent")


def sign_intent(settings: Settings, intent: UserIntent) -> str:
    return cast(
        str,
        get_intent_serializer(settings).dumps(
            {"resource_id": intent.resource_id, "starts": intent.starts, "ends": intent.ends}
        ),
    )


def load_intent(settings: Settings, raw: str | None) -> UserIntent | None:
    if not raw:
        return None
    try:
        data = get_intent_serializer(settings).loads(raw, max_age=INTENT_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or "resource_id" not in data:
        return None
    return UserIntent(
        resource_id=int(data["resource_id"]),
        starts=data.get("starts"),
        ends=data.get("ends"),
    )

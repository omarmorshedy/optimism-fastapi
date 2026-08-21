"""Theme tests: both UI themes render the same routes with the same data
(WEB_THEME=modern is the default; WEB_THEME=legacy uses the Bootstrap look)."""

from __future__ import annotations

import datetime as dt

import pytest
from app.core.config import Settings
from app.core.security import hash_password
from app.main import create_app
from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD


@pytest.fixture()
def legacy_app(settings, db_session):
    """An app instance forced to the legacy (Bootstrap) theme."""
    from tests.factories import create_resource, create_resource_type, create_window

    create_resource_type(db_session, name="room")
    create_resource(db_session, name="Dinky", capacity=1)
    create_window(
        db_session,
        1,
        weekday=1,
        starts=dt.time(9, 30, tzinfo=dt.UTC),
        ends=dt.time(10, 30, tzinfo=dt.UTC),
    )
    db_session.commit()

    theme_settings = Settings(
        database_url=settings.database_url,
        auto_migrate=False,
        email_worker_enabled=False,
        admin_password_hash=hash_password(TEST_PASSWORD),
        session_secret="s" * 32,
        environment="test",
        web_theme="legacy",
        smtp_host="",
    )
    return create_app(theme_settings)


@pytest.fixture()
def legacy_client(legacy_app):
    with TestClient(legacy_app) as client:
        yield client


class TestLegacyTheme:
    def test_home_renders_bootstrap_layout(self, legacy_client) -> None:
        response = legacy_client.get("/")
        assert response.status_code == 200
        # Same content, Bootstrap look: jumbotron + vendored bootstrap css.
        assert "Booking resources at DoES Liverpool" in response.text
        assert 'class="jumbotron"' in response.text
        assert "/static/legacy/css/optimism.css" in response.text

    def test_select_a_resource(self, legacy_client) -> None:
        response = legacy_client.get("/select-a-resource")
        assert response.status_code == 200
        assert "Step 1 of 3" in response.text
        assert "Dinky" in response.text
        assert 'class="btn btn-primary"' in response.text

    def test_calendar_js_is_versioned(self, legacy_client, client) -> None:
        """The calendar JS is cache-busted so users never run a stale renderer
        (which could show past slots as bookable)."""
        assert "/static/js/calendar.js?v=2" in legacy_client.get("/select-a-time?resource=1").text
        assert "/static/js/calendar.js?v=2" in client.get("/select-a-time?resource=1").text

    def test_select_a_time(self, legacy_client, frozen_week) -> None:
        response = legacy_client.get("/select-a-time?resource=1")
        assert response.status_code == 200
        assert "Step 2 of 3" in response.text
        # Server-rendered week uses the SAME unified markup the JS produces,
        # so navigating weeks never changes the look.
        assert 'class="slot-list"' in response.text
        assert 'class="slot-button"' in response.text
        assert "btn btn-sm btn-primary slot-button" not in response.text
        assert legacy_client.cookies.get("user_intent")

    def test_admin_login_page(self, legacy_client) -> None:
        response = legacy_client.get("/admin/login")
        assert response.status_code == 200
        assert "Sign in" in response.text
        assert 'class="form-signin' in response.text

    def test_admin_pages_render(self, legacy_client) -> None:
        legacy_client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        dashboard = legacy_client.get("/admin/")
        assert dashboard.status_code == 200
        assert "Dashboard" in dashboard.text
        resources_page = legacy_client.get("/admin/resources")
        assert "Resources" in resources_page.text

    def test_full_booking_flow(self, legacy_client, frozen_week) -> None:
        legacy_client.get("/select-a-time?resource=1")
        details = legacy_client.post(
            "/your-details",
            data={"resource": "1", "slot": "2030-01-07T09:30:00|2030-01-07T10:30:00"},
        )
        assert details.status_code == 200
        assert "Step 3 of 3" in details.text
        confirmation = legacy_client.post(
            "/confirmation",
            data={
                "resourceId": "1",
                "name": "Legacy User",
                "email": "legacy@example.org",
                "starts": "2030-01-07T09:30:00",
                "ends": "2030-01-07T10:30:00",
                "notes": "",
            },
        )
        assert confirmation.status_code == 200
        assert "Booking Confirmed!" in confirmation.text
        assert "cancelBookingModal" in confirmation.text
        assert "/cancel-booking/" in confirmation.text
        # Visible fallback link in case the modal cannot open.
        assert "Open the cancellation page" in confirmation.text


class TestThemeSelection:
    def test_default_theme_is_modern(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "/static/css/optimism.css" in response.text  # modern stylesheet
        assert "/static/legacy/" not in response.text

    def test_invalid_theme_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(web_theme="svelte", _env_file=None)

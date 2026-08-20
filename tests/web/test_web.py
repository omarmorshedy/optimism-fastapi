"""Browser-flow tests for the server-rendered web layer (public + admin)."""

from __future__ import annotations

import datetime as dt

import pytest

from tests.conftest import TEST_PASSWORD

MONDAY = dt.date(2030, 1, 7)


@pytest.fixture()
def seeded(app, db_session):
    from tests.factories import create_resource, create_resource_type, create_window

    resource_type = create_resource_type(db_session, name="room")
    create_resource(db_session, name="Dinky", capacity=1, resource_type_id=resource_type.id)
    create_window(
        db_session,
        1,
        weekday=1,
        starts=dt.time(9, 30, tzinfo=dt.UTC),
        ends=dt.time(10, 30, tzinfo=dt.UTC),
    )
    db_session.commit()
    return app


class TestPublicFlow:
    def test_home(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "Booking resources at DoES Liverpool" in response.text

    def test_select_a_resource(self, seeded, client) -> None:
        response = client.get("/select-a-resource")
        assert response.status_code == 200
        assert "Dinky" in response.text

    def test_select_a_time_sets_intent_cookie(self, seeded, client) -> None:
        response = client.get("/select-a-time?resource=1")
        assert response.status_code == 200
        assert "Dinky" in response.text
        assert client.cookies.get("user_intent")

    def test_select_a_time_renders_initial_week(self, seeded, client) -> None:
        response = client.get("/select-a-time?resource=1")
        assert response.status_code == 200
        # The initial week is rendered server-side (no-JS fallback).
        assert "slot-button" in response.text

    def test_select_a_time_missing_resource(self, client) -> None:
        response = client.get("/select-a-time")
        assert response.status_code == 400
        assert "No resource was selected." in response.text

    def test_your_details_flow(self, seeded, client) -> None:
        client.get("/select-a-time?resource=1")
        response = client.post(
            "/your-details",
            data={
                "resource": "1",
                "slot": f"{MONDAY.isoformat()}T09:30:00|{MONDAY.isoformat()}T10:30:00",
            },
        )
        assert response.status_code == 200
        assert "Your details" in response.text

    def test_your_details_rejects_unmatched_resource(self, seeded, client) -> None:
        client.get("/select-a-time?resource=1")
        response = client.post(
            "/your-details",
            data={"resource": "2", "slot": "2030-01-07T09:30:00|2030-01-07T10:30:00"},
        )
        assert response.status_code == 400

    def test_confirmation_creates_booking(self, seeded, client) -> None:
        client.get("/select-a-time?resource=1")
        response = client.post(
            "/confirmation",
            data={
                "resourceId": "1",
                "name": "Web User",
                "email": "web@example.org",
                "starts": f"{MONDAY.isoformat()}T09:30:00",
                "ends": f"{MONDAY.isoformat()}T10:30:00",
                "notes": "From the web",
            },
        )
        assert response.status_code == 200
        assert "Booking confirmed" in response.text
        assert "Web User" in response.text
        assert "/cancel-booking/" in response.text

    def test_cancel_page_requires_confirmation(self, seeded, client) -> None:
        # Create a booking via the web flow to obtain the raw token.
        client.get("/select-a-time?resource=1")
        confirmation = client.post(
            "/confirmation",
            data={
                "resourceId": "1",
                "name": "Web User",
                "email": "web@example.org",
                "starts": f"{MONDAY.isoformat()}T09:30:00",
                "ends": f"{MONDAY.isoformat()}T10:30:00",
                "notes": "",
            },
        )
        import re

        match = re.search(r"/cancel-booking/([A-Za-z0-9_-]+)", confirmation.text)
        assert match, "cancellation link missing from confirmation page"
        token = match.group(1)

        # GET shows the confirmation page and does NOT cancel.
        page = client.get(f"/cancel-booking/{token}")
        assert page.status_code == 200
        assert "Are you sure you want to cancel" in page.text

        # The booking is still active.
        lookup = client.get(f"/api/v1/bookings/lookup/{token}")
        assert lookup.json()["cancelled"] is False

        # POST performs the cancellation.
        page = client.post(
            f"/cancel-booking/{token}", data={"csrf_token": client.cookies.get("csrf_token") or ""}
        )
        assert page.status_code == 200
        assert "cancelled" in page.text.lower()
        lookup = client.get(f"/api/v1/bookings/lookup/{token}")
        assert lookup.json()["cancelled"] is True

    def test_unknown_cancel_token_page(self, client) -> None:
        response = client.get("/cancel-booking/unknown-token")
        assert response.status_code == 404


class TestAdminPages:
    def test_admin_requires_login(self, client) -> None:
        # Redirects ultimately land on the login page.
        response = client.get("/admin/")
        assert response.status_code == 200
        assert "Admin login" in response.text

    def test_login_page(self, client) -> None:
        response = client.get("/admin/login")
        assert response.status_code == 200
        assert "Admin login" in response.text

    def test_login_post_sets_cookies(self, client) -> None:
        response = client.post(
            "/admin/login",
            data={"password": TEST_PASSWORD, "redirect": "/admin/"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert client.cookies.get("optimism_admin_session")
        assert client.cookies.get("csrf_token")

    def test_login_wrong_password(self, client) -> None:
        response = client.post("/admin/login", data={"password": "nope", "redirect": "/admin/"})
        assert response.status_code == 200
        assert "Invalid credentials." in response.text

    def test_dashboard_after_login(self, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        response = client.get("/admin/")
        assert response.status_code == 200
        assert "Dashboard" in response.text

    def test_logout(self, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        csrf = client.cookies.get("csrf_token")
        response = client.post("/admin/logout", data={"csrf_token": csrf}, follow_redirects=False)
        assert response.status_code == 303
        assert client.get("/admin/", follow_redirects=False).status_code in (302, 303, 307)

    def test_logout_requires_csrf(self, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        response = client.post("/admin/logout", data={"csrf_token": ""})
        assert response.status_code == 403

    def test_resource_type_crud_flow(self, seeded, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        csrf = client.cookies.get("csrf_token")
        # Create
        response = client.post(
            "/admin/resource-types/create",
            data={"name": "laser-cutter", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        listing = client.get("/admin/resource-types")
        assert "laser-cutter" in listing.text
        # Edit
        response = client.post(
            "/admin/resource-types/2/edit",
            data={"name": "laser", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "laser" in client.get("/admin/resource-types").text
        # Delete
        response = client.post(
            "/admin/resource-types/2/delete", data={"csrf_token": csrf}, follow_redirects=False
        )
        assert response.status_code == 303
        assert "laser" not in client.get("/admin/resource-types").text

    def test_resource_crud_flow(self, seeded, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        csrf = client.cookies.get("csrf_token")
        response = client.post(
            "/admin/resources/create",
            data={"name": "Sophia", "capacity": "2", "resourceTypeId": "1", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        listing = client.get("/admin/resources")
        assert "Sophia" in listing.text
        # Edit
        response = client.post(
            "/admin/resources/2/edit",
            data={"name": "Sophia II", "capacity": "3", "resourceTypeId": "", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Sophia II" in client.get("/admin/resources").text

    def test_window_replacement_flow(self, seeded, client) -> None:
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        csrf = client.cookies.get("csrf_token")
        page = client.get("/admin/resources/1/windows")
        assert page.status_code == 200
        response = client.post(
            "/admin/resources/1/windows",
            data={
                "csrf_token": csrf,
                "weekday": ["1", "2"],
                "starts": ["09:30", "14:00"],
                "ends": ["10:30", "15:00"],
                "name": ["Morning", "Afternoon"],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Afternoon" in client.get("/admin/resources/1/windows").text

    def test_bookings_page(self, seeded, client, db_session) -> None:
        from tests.factories import create_booking

        create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        response = client.get("/admin/bookings")
        assert response.status_code == 200
        assert "A Name" in response.text

    def test_booking_detail_and_admin_cancel(self, seeded, client, db_session) -> None:
        from tests.factories import create_booking

        booking = create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        client.post("/admin/login", data={"password": TEST_PASSWORD}, follow_redirects=False)
        csrf = client.cookies.get("csrf_token")
        detail = client.get(f"/admin/bookings/{booking.id}")
        assert detail.status_code == 200
        assert "A Name" in detail.text
        response = client.post(
            f"/admin/bookings/{booking.id}/cancel",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "Cancelled" in client.get(f"/admin/bookings/{booking.id}").text

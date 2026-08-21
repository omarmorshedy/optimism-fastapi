"""API contract tests for /api/v1/bookings — creation, lookup, amend, cancel
(API_SPEC §3.4-3.7, §5, §7) and the admin booking endpoints (API_SPEC §4.5)."""

from __future__ import annotations

import datetime as dt

import pytest

from tests.conftest import login

MONDAY = dt.date(2030, 1, 7)  # a Monday
SLOT_STARTS = dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC)
SLOT_ENDS = dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC)

BOOKING_PAYLOAD = {
    "resourceId": 1,
    "email": "someone@example.org",
    "name": "A Name",
    "notes": "Some text",
    "starts": "2030-01-07T09:30:00",
    "ends": "2030-01-07T10:30:00",
}


@pytest.fixture()
def seeded(admin_client, db_session):
    """One resource (capacity 1) with a Monday 09:30-10:30 window."""
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
    return admin_client


class TestCreateBooking:
    def test_valid_creation_returns_token_once(self, seeded) -> None:
        response = seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        assert response.status_code == 201
        body = response.json()
        assert body["id"] == 1
        assert body["resourceId"] == 1
        assert body["resourceName"] == "Dinky"
        assert body["email"] == "someone@example.org"
        assert body["name"] == "A Name"
        assert body["notes"] == "Some text"
        assert body["starts"] == "2030-01-07T09:30:00.000Z"
        assert body["ends"] == "2030-01-07T10:30:00.000Z"
        assert body["cancelled"] is False
        assert body["createdAt"].endswith("Z")
        token = body["token"]
        assert len(token) >= 40
        # The token must never appear in later responses.
        lookup = seeded.get(f"/api/v1/bookings/lookup/{token}")
        assert "token" not in lookup.json()
        admin_list = seeded.get("/api/v1/bookings")
        assert "token" not in admin_list.json()[0]

    def test_token_lookup_works_immediately_after_creation(self, seeded) -> None:
        """The creation transaction is committed before the response is sent,
        so the returned cancellation token is usable right away (regression:
        a yield-dependency teardown commit used to race the insert)."""
        response = seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        assert response.status_code == 201
        token = response.json()["token"]
        # No sleep: the very next request must see the booking.
        lookup = seeded.get(f"/api/v1/bookings/lookup/{token}")
        assert lookup.status_code == 200
        assert lookup.json()["cancelled"] is False

    def test_invalid_email_is_422_not_500(self, seeded) -> None:
        """A syntactically weak email (john@gmail passes HTML5 UI checks but
        fails email-validator) returns a 422 problem, never a 500."""
        payload = {**BOOKING_PAYLOAD, "email": "john@gmail"}
        response = seeded.post("/api/v1/bookings", json=payload)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")

    def test_email_outbox_row_created(self, seeded, db_session) -> None:
        seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        db_session.expire_all()
        from app.models.email_outbox import EmailOutbox
        from sqlalchemy import select

        row = db_session.scalar(select(EmailOutbox))
        assert row is not None
        assert row.status == "pending"
        assert row.subject == "Booking Confirmation - Dinky"
        assert "Welcome A Name!" in row.body
        assert row.to_addr == "someone@example.org"

    def test_missing_field_422(self, seeded) -> None:
        payload = dict(BOOKING_PAYLOAD)
        del payload["notes"]
        assert seeded.post("/api/v1/bookings", json=payload).status_code == 422

    def test_extra_field_422(self, seeded) -> None:
        payload = {**BOOKING_PAYLOAD, "shouldNot": "be here"}
        assert seeded.post("/api/v1/bookings", json=payload).status_code == 422

    def test_invalid_email_422(self, seeded) -> None:
        payload = {**BOOKING_PAYLOAD, "email": "not-an-email"}
        assert seeded.post("/api/v1/bookings", json=payload).status_code == 422

    def test_unknown_resource_404(self, seeded) -> None:
        payload = {**BOOKING_PAYLOAD, "resourceId": 9999}
        response = seeded.post("/api/v1/bookings", json=payload)
        assert response.status_code == 404
        assert response.json()["detail"] == "Resource not found."

    def test_end_before_start_422(self, seeded) -> None:
        payload = {
            **BOOKING_PAYLOAD,
            "starts": "2030-01-07T10:30:00",
            "ends": "2030-01-07T09:30:00",
        }
        response = seeded.post("/api/v1/bookings", json=payload)
        assert response.status_code == 422
        assert response.json()["detail"] == "End time must be after start time."

    def test_must_exactly_match_window_422(self, seeded) -> None:
        # 09:30-10:00 is inside the 09:30-10:30 window but not an exact match.
        payload = {
            **BOOKING_PAYLOAD,
            "starts": "2030-01-07T09:30:00",
            "ends": "2030-01-07T10:00:00",
        }
        response = seeded.post("/api/v1/bookings", json=payload)
        assert response.status_code == 422

    def test_non_window_time_422(self, seeded) -> None:
        payload = {
            **BOOKING_PAYLOAD,
            "starts": "2030-01-07T11:00:00",
            "ends": "2030-01-07T12:00:00",
        }
        assert seeded.post("/api/v1/bookings", json=payload).status_code == 422

    def test_capacity_full_409(self, seeded) -> None:
        seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        response = seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")
        assert response.json()["detail"] == (
            "This time slot is already fully booked. Please select another time."
        )

    def test_closed_exception_409(self, seeded, db_session) -> None:
        from tests.factories import create_exception

        create_exception(db_session, 1, MONDAY, kind="closed", reason="Holiday")
        db_session.commit()
        response = seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
        assert response.status_code == 409

    def test_open_exception_allows_booking(self, seeded, db_session) -> None:
        # The window is already on Monday; an open exception keeps it bookable.
        from tests.factories import create_exception

        create_exception(db_session, 1, MONDAY, kind="open", reason="Special")
        db_session.commit()
        assert seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD).status_code == 201


class TestCreateRateLimit:
    def test_rate_limit_returns_429(self, db_session, settings) -> None:
        from app.core.config import Settings
        from app.core.security import hash_password
        from app.db.base import Base
        from app.db.engine import get_engine
        from app.main import create_app
        from fastapi.testclient import TestClient
        from sqlalchemy import text

        from tests.factories import create_resource, create_window

        limited_settings = Settings(
            database_url="sqlite:///:memory:",
            auto_migrate=False,
            email_worker_enabled=False,
            admin_password_hash=hash_password("test-password"),
            session_secret="s" * 32,
            environment="test",
            rate_limit_booking_create="3/minute",
            smtp_host="",
        )
        engine = get_engine(limited_settings)
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(
                text("INSERT OR IGNORE INTO alembic_version (version_num) VALUES ('0001')")
            )
        from app.db.engine import get_session_factory

        factory = get_session_factory(limited_settings)
        session = factory()
        create_resource(session, name="Dinky", capacity=5)
        create_window(
            session, 1, starts=dt.time(9, 30, tzinfo=dt.UTC), ends=dt.time(10, 30, tzinfo=dt.UTC)
        )
        session.commit()
        session.close()

        app = create_app(limited_settings)
        with TestClient(app) as client:
            for _ in range(3):
                assert client.post("/api/v1/bookings", json=BOOKING_PAYLOAD).status_code == 201
            response = client.post("/api/v1/bookings", json=BOOKING_PAYLOAD)
            assert response.status_code == 429
            assert response.json()["type"].endswith("/rate-limited")


class TestLookupCancelAmend:
    def _create(self, seeded) -> str:
        return seeded.post("/api/v1/bookings", json=BOOKING_PAYLOAD).json()["token"]

    def test_lookup_valid(self, seeded) -> None:
        token = self._create(seeded)
        response = seeded.get(f"/api/v1/bookings/lookup/{token}")
        assert response.status_code == 200
        body = response.json()
        assert body["resourceName"] == "Dinky"
        assert "token" not in body

    def test_lookup_unknown_token_404(self, seeded) -> None:
        response = seeded.get("/api/v1/bookings/lookup/unknown-token")
        assert response.status_code == 404
        assert response.json()["detail"] == "No booking found with this token."

    def test_cancel_success(self, seeded) -> None:
        token = self._create(seeded)
        response = seeded.post(f"/api/v1/bookings/cancel/{token}")
        assert response.status_code == 200
        body = response.json()
        assert body["message"] == "Booking cancelled successfully."
        assert body["booking"]["cancelled"] is True
        assert "token" not in body["booking"]

    def test_cancel_is_idempotent(self, seeded) -> None:
        token = self._create(seeded)
        first = seeded.post(f"/api/v1/bookings/cancel/{token}")
        second = seeded.post(f"/api/v1/bookings/cancel/{token}")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["message"] == "Booking cancelled successfully."

    def test_cancel_unknown_token_404(self, seeded) -> None:
        assert seeded.post("/api/v1/bookings/cancel/unknown").status_code == 404

    def test_cancel_after_cutoff_409(self, seeded) -> None:
        """Bookings whose start is within (or past) the cutoff cannot be
        cancelled by the user (API_SPEC §1.8, §7)."""
        today = dt.date.today()
        most_recent_monday = today - dt.timedelta(days=today.weekday())  # weekday(): Mon=0
        payload = {
            **BOOKING_PAYLOAD,
            "starts": f"{most_recent_monday.isoformat()}T09:30:00",
            "ends": f"{most_recent_monday.isoformat()}T10:30:00",
        }
        created = seeded.post("/api/v1/bookings", json=payload)
        # The Monday window matches any Monday, including past ones.
        assert created.status_code == 201, created.text
        token = created.json()["token"]
        response = seeded.post(f"/api/v1/bookings/cancel/{token}")
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")

    def test_cancel_before_cutoff_succeeds(self, seeded) -> None:
        token = self._create(seeded)  # 2030 booking: far in the future
        assert seeded.post(f"/api/v1/bookings/cancel/{token}").status_code == 200

    def test_amend_details(self, seeded) -> None:
        token = self._create(seeded)
        response = seeded.put(
            f"/api/v1/bookings/amend/{token}",
            json={"name": "New Name", "notes": "New notes", "email": "new@example.org"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "New Name"
        assert body["notes"] == "New notes"
        assert body["email"] == "new@example.org"
        assert "token" not in body

    def test_amend_times_revalidated(self, seeded, db_session) -> None:
        from tests.factories import create_window

        # Add a Tuesday window so a valid move exists.
        create_window(
            db_session,
            1,
            weekday=2,
            starts=dt.time(9, 30, tzinfo=dt.UTC),
            ends=dt.time(10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        token = self._create(seeded)
        response = seeded.put(
            f"/api/v1/bookings/amend/{token}",
            json={"starts": "2030-01-08T09:30:00", "ends": "2030-01-08T10:30:00"},
        )
        assert response.status_code == 200
        assert response.json()["starts"] == "2030-01-08T09:30:00.000Z"

    def test_amend_to_unavailable_409(self, seeded, db_session) -> None:
        from tests.factories import create_booking, create_window

        create_window(
            db_session,
            1,
            weekday=2,
            starts=dt.time(9, 30, tzinfo=dt.UTC),
            ends=dt.time(10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        # Someone else already booked the Tuesday slot.
        create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 8, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 8, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        token = self._create(seeded)
        response = seeded.put(
            f"/api/v1/bookings/amend/{token}",
            json={"starts": "2030-01-08T09:30:00", "ends": "2030-01-08T10:30:00"},
        )
        assert response.status_code == 409

    def test_amend_cancelled_booking_409(self, seeded) -> None:
        token = self._create(seeded)
        seeded.post(f"/api/v1/bookings/cancel/{token}")
        response = seeded.put(f"/api/v1/bookings/amend/{token}", json={"name": "X"})
        assert response.status_code == 409

    def test_amend_partial_times_422(self, seeded) -> None:
        token = self._create(seeded)
        response = seeded.put(
            f"/api/v1/bookings/amend/{token}", json={"starts": "2030-01-08T09:30:00"}
        )
        assert response.status_code == 422

    def test_amend_unknown_token_404(self, seeded) -> None:
        assert seeded.put("/api/v1/bookings/amend/unknown", json={"name": "X"}).status_code == 404


class TestAdminBookings:
    def test_list_requires_auth(self, client) -> None:
        assert client.get("/api/v1/bookings").status_code == 401

    def test_get_requires_auth(self, client) -> None:
        assert client.get("/api/v1/bookings/1").status_code == 401

    def test_list_ordered_by_starts_desc(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 8, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 8, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        response = admin_client.get("/api/v1/bookings")
        assert response.status_code == 200
        assert next(b["starts"] for b in response.json()).startswith("2030-01-08")

    def test_list_filters_and_pagination(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        for day in (7, 8, 9):
            create_booking(
                db_session,
                1,
                dt.datetime(2030, 1, day, 9, 30, tzinfo=dt.UTC),
                dt.datetime(2030, 1, day, 10, 30, tzinfo=dt.UTC),
                email=f"user{day}@example.org",
                name=f"User {day}",
            )
        db_session.commit()
        # email substring filter
        response = admin_client.get("/api/v1/bookings", params={"email": "user8"})
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "User 8"
        # pagination: limit 2, offset 1 → X-Total-Count = 3
        response = admin_client.get("/api/v1/bookings", params={"limit": 2, "offset": 1})
        assert response.headers["X-Total-Count"] == "3"
        assert len(response.json()) == 2
        # startsFrom / startsTo
        response = admin_client.get(
            "/api/v1/bookings",
            params={"startsFrom": "2030-01-08T00:00:00", "startsTo": "2030-01-08T23:59:59"},
        )
        assert len(response.json()) == 1
        # cancelled filter
        response = admin_client.get("/api/v1/bookings", params={"cancelled": "true"})
        assert response.json() == []

    def test_get_detail_no_token(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        booking = create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        response = admin_client.get(f"/api/v1/bookings/{booking.id}")
        assert response.status_code == 200
        assert "token" not in response.json()
        assert response.json()["resourceName"] == "R"

    def test_admin_amend_past_booking_allowed(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        past_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)
        booking = create_booking(db_session, 1, past_start, past_start + dt.timedelta(hours=1))
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.put(
            f"/api/v1/bookings/{booking.id}", json={"name": "Admin Updated"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Admin Updated"

    def test_admin_cancel_idempotent(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        booking = create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        headers = login(admin_client)
        first = admin_client.post(f"/api/v1/bookings/{booking.id}/cancel", headers=headers)
        second = admin_client.post(f"/api/v1/bookings/{booking.id}/cancel", headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200

    def test_admin_delete_is_soft_and_frees_capacity(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource, create_window

        create_resource(db_session, name="R", capacity=1)
        create_window(db_session, 1)
        booking = create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.delete(f"/api/v1/bookings/{booking.id}", headers=headers)
        assert response.status_code == 204
        # Booking is soft-deleted: still fetchable, marked cancelled, and the
        # slot is available again.
        detail = admin_client.get(f"/api/v1/bookings/{booking.id}").json()
        assert detail["cancelled"] is True
        calendar = admin_client.get("/api/v1/calendar/2030-01-07/2030-01-08/1").json()
        slot = calendar["dates"][0]["resources"][0]["slots"][0]
        assert slot["status"] == "available"

    def test_admin_delete_404(self, admin_client) -> None:
        headers = login(admin_client)
        assert admin_client.delete("/api/v1/bookings/9999", headers=headers).status_code == 404

    def test_write_endpoints_require_csrf(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource

        create_resource(db_session, name="R", capacity=5)
        booking = create_booking(
            db_session,
            1,
            dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        # Logged in but no CSRF header.
        assert (
            admin_client.put(f"/api/v1/bookings/{booking.id}", json={"name": "X"}).status_code
            == 403
        )
        assert admin_client.post(f"/api/v1/bookings/{booking.id}/cancel").status_code == 403
        assert admin_client.delete(f"/api/v1/bookings/{booking.id}").status_code == 403

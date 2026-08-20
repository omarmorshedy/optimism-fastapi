"""API contract tests for GET /api/v1/calendar/{start}/{end}/{resourceId}
(API_SPEC §3.3, §6) — ports the legacy calendar tests with corrected semantics
(422 for malformed input, corrected overlap predicate, UTC rendering)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

WINDOW_MONDAY_AM = {"weekday": 1, "starts": "09:30", "ends": "10:30"}  # Monday
WINDOW_MONDAY_PM = {"weekday": 1, "starts": "14:00", "ends": "15:00"}
WINDOW_SUNDAY = {"weekday": 0, "starts": "09:30", "ends": "10:30"}


@pytest.fixture()
def seeded(admin_client, db_session):
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


def _day_slots(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten all slots for the returned dates."""
    return [slot for day in payload["dates"] for slot in day["resources"][0]["slots"]]


class TestParameterValidation:
    @pytest.mark.parametrize(
        ("start", "end", "resource", "expected"),
        [
            ("2022-03-17", "2022-03-18", 1, 200),
            ("2022-17-03", "2022-17-04", 1, 422),  # malformed start
            ("2022-03-17", "2022-", 1, 422),  # malformed end
            ("2022-03-17", "2022-03-18", -1, 422),  # invalid resource id
            ("2022-03-18", "2022-03-17", 1, 422),  # start > end
            ("2022-03-17", "2022-03-18", 4000, 404),  # nonexistent resource
        ],
    )
    def test_status_codes(self, seeded, start: str, end: str, resource: int, expected: int) -> None:
        response = seeded.get(f"/api/v1/calendar/{start}/{end}/{resource}")
        assert response.status_code == expected

    def test_start_equals_end_is_422(self, seeded) -> None:
        response = seeded.get("/api/v1/calendar/2022-03-17/2022-03-17/1")
        assert response.status_code == 422

    def test_404_detail(self, seeded) -> None:
        response = seeded.get("/api/v1/calendar/2022-03-17/2022-03-18/4000")
        assert response.json()["detail"] == "No such resource."


class TestResponseShape:
    def test_legacy_shape(self, seeded) -> None:
        # 2022-03-17 is a Thursday (weekday 4): the Monday window does not apply.
        response = seeded.get("/api/v1/calendar/2022-03-17/2022-03-18/1")
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"dates"}
        assert len(body["dates"]) == 2
        day = body["dates"][0]
        assert day["date"] == "2022-03-17T00:00:00.000Z"
        assert day["resources"][0]["resourceName"] == "Dinky"
        assert day["resources"][0]["slots"] == []

    def test_slot_instances_rendered_in_utc(self, seeded) -> None:
        # 2022-03-21 is a Monday (weekday 1).
        response = seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1")
        slots = _day_slots(response.json())
        assert len(slots) == 1
        assert slots[0] == {
            "starts": "2022-03-21T09:30:00.000Z",
            "ends": "2022-03-21T10:30:00.000Z",
            "status": "available",
        }

    def test_available_when_below_capacity(self, seeded) -> None:
        assert (
            _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())[0]["status"]
            == "available"
        )

    def test_unavailable_when_capacity_reached(self, seeded, db_session) -> None:
        from tests.factories import create_booking

        create_booking(
            db_session,
            1,
            dt.datetime(2022, 3, 21, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2022, 3, 21, 10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        slots = _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())
        assert slots[0]["status"] == "unavailable"

    def test_cancelled_bookings_do_not_count(self, seeded, db_session) -> None:
        from tests.factories import create_booking

        create_booking(
            db_session,
            1,
            dt.datetime(2022, 3, 21, 9, 30, tzinfo=dt.UTC),
            dt.datetime(2022, 3, 21, 10, 30, tzinfo=dt.UTC),
            cancelled=True,
        )
        db_session.commit()
        slots = _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())
        assert slots[0]["status"] == "available"

    def test_spanning_booking_counts_at_boundaries(self, seeded, db_session) -> None:
        """A booking spanning the whole query range must make the slot
        unavailable (legacy boundary bug fix)."""
        from tests.factories import create_booking

        # Booking starts before the range and ends after it.
        create_booking(
            db_session,
            1,
            dt.datetime(2022, 3, 21, 8, 0, tzinfo=dt.UTC),
            dt.datetime(2022, 3, 21, 12, 0, tzinfo=dt.UTC),
        )
        db_session.commit()
        slots = _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())
        assert slots[0]["status"] == "unavailable"

    def test_sunday_weekday_convention(self, seeded, db_session) -> None:
        from tests.factories import create_window

        create_window(
            db_session,
            1,
            weekday=0,
            starts=dt.time(9, 30, tzinfo=dt.UTC),
            ends=dt.time(10, 30, tzinfo=dt.UTC),
        )
        db_session.commit()
        # 2022-03-20 is a Sunday (weekday 0).
        body = seeded.get("/api/v1/calendar/2022-03-20/2022-03-21/1").json()
        assert len(body["dates"][0]["resources"][0]["slots"]) == 1

    def test_multi_day_range_includes_each_day(self, seeded) -> None:
        # 2022-03-20 (Sun, wd 0) and 2022-03-21 (Mon, wd 1).
        body = seeded.get("/api/v1/calendar/2022-03-20/2022-03-21/1").json()
        assert len(body["dates"]) == 2
        assert body["dates"][0]["date"] == "2022-03-20T00:00:00.000Z"
        assert body["dates"][1]["date"] == "2022-03-21T00:00:00.000Z"

    def test_closed_exception_removes_slot(self, seeded, db_session) -> None:
        from tests.factories import create_exception

        create_exception(db_session, 1, dt.date(2022, 3, 21), kind="closed", reason="Holiday")
        db_session.commit()
        slots = _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())
        assert slots == []

    def test_open_exception_keeps_slot(self, seeded, db_session) -> None:
        from tests.factories import create_exception

        create_exception(db_session, 1, dt.date(2022, 3, 21), kind="open", reason="Special")
        db_session.commit()
        slots = _day_slots(seeded.get("/api/v1/calendar/2022-03-21/2022-03-22/1").json())
        assert len(slots) == 1

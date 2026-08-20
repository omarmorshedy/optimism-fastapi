"""API contract tests for /api/v1/availability-windows and
/api/v1/availability-exceptions (API_SPEC §4.4, ADR-008)."""

from __future__ import annotations

import pytest

from tests.conftest import login


@pytest.fixture()
def seeded(admin_client, db_session):
    from tests.factories import create_resource, create_resource_type

    resource_type = create_resource_type(db_session, name="room")
    create_resource(db_session, name="Dinky", capacity=1, resource_type_id=resource_type.id)
    db_session.commit()
    return admin_client


class TestWindowsAdminOnly:
    def test_list_requires_auth(self, client) -> None:
        assert client.get("/api/v1/availability-windows").status_code == 401

    def test_list_empty(self, seeded) -> None:
        response = seeded.get("/api/v1/availability-windows")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_filter_by_resource(self, admin_client, db_session) -> None:
        from tests.factories import create_resource, create_window

        r1 = create_resource(db_session, name="One", capacity=1)
        r2 = create_resource(db_session, name="Two", capacity=1)
        create_window(db_session, r1.id)
        create_window(db_session, r2.id)
        db_session.commit()
        response = admin_client.get(f"/api/v1/availability-windows?resourceId={r1.id}")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["resourceId"] == r1.id


class TestWindowCreate:
    def test_create_valid(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-windows",
            json={
                "resourceId": 1,
                "weekday": 1,
                "starts": "09:30",
                "ends": "10:00",
                "name": "Morning",
            },
            headers=headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["resourceId"] == 1
        assert body["weekday"] == 1
        assert body["starts"] == "09:30"
        assert body["ends"] == "10:00"
        assert body["name"] == "Morning"

    def test_create_bad_time_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "25:00", "ends": "10:00"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_ends_before_starts_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "10:00", "ends": "09:30"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_weekday_out_of_range_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 7, "starts": "09:30", "ends": "10:00"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_unknown_resource_404(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 9999, "weekday": 1, "starts": "09:30", "ends": "10:00"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_create_overlap_409(self, seeded) -> None:
        headers = login(seeded)
        seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "11:00"},
            headers=headers,
        )
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "10:00", "ends": "12:00"},
            headers=headers,
        )
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")

    def test_touching_windows_do_not_overlap(self, seeded) -> None:
        headers = login(seeded)
        seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "11:00"},
            headers=headers,
        )
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "11:00", "ends": "12:00"},
            headers=headers,
        )
        assert response.status_code == 201  # half-open intervals do not overlap

    def test_different_weekday_ok(self, seeded) -> None:
        headers = login(seeded)
        seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "11:00"},
            headers=headers,
        )
        response = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 2, "starts": "09:30", "ends": "11:00"},
            headers=headers,
        )
        assert response.status_code == 201


class TestWindowUpdateDelete:
    def test_get_404(self, seeded) -> None:
        assert seeded.get("/api/v1/availability-windows/9999").status_code == 404

    def test_update_valid(self, seeded) -> None:
        headers = login(seeded)
        created = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "10:00"},
            headers=headers,
        ).json()
        response = seeded.put(
            f"/api/v1/availability-windows/{created['id']}",
            json={"starts": "10:30", "ends": "11:30"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["starts"] == "10:30"

    def test_update_overlap_409(self, seeded) -> None:
        headers = login(seeded)
        first = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "10:30"},
            headers=headers,
        ).json()
        seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "11:00", "ends": "12:00"},
            headers=headers,
        )
        response = seeded.put(
            f"/api/v1/availability-windows/{first['id']}",
            json={"ends": "11:30"},
            headers=headers,
        )
        assert response.status_code == 409

    def test_delete_valid_204(self, seeded) -> None:
        headers = login(seeded)
        created = seeded.post(
            "/api/v1/availability-windows",
            json={"resourceId": 1, "weekday": 1, "starts": "09:30", "ends": "10:00"},
            headers=headers,
        ).json()
        assert (
            seeded.delete(
                f"/api/v1/availability-windows/{created['id']}", headers=headers
            ).status_code
            == 204
        )
        assert seeded.get(f"/api/v1/availability-windows/{created['id']}").status_code == 404

    def test_delete_404(self, seeded) -> None:
        headers = login(seeded)
        assert (
            seeded.delete("/api/v1/availability-windows/9999", headers=headers).status_code == 404
        )


class TestResourceWindowsEndpoint:
    def test_get_windows_requires_auth(self, client) -> None:
        assert client.get("/api/v1/resources/1/windows").status_code == 401

    def test_get_windows_unknown_resource_404(self, seeded) -> None:
        assert seeded.get("/api/v1/resources/9999/windows").status_code == 404

    def test_put_replaces_all_windows(self, seeded) -> None:
        headers = login(seeded)
        body = [
            {"weekday": 1, "starts": "09:30", "ends": "10:00", "name": "A"},
            {"weekday": 1, "starts": "10:30", "ends": "11:00", "name": "B"},
        ]
        response = seeded.put("/api/v1/resources/1/windows", json=body, headers=headers)
        assert response.status_code == 204
        windows = seeded.get("/api/v1/resources/1/windows").json()
        assert len(windows) == 2

    def test_put_overlap_in_set_409(self, seeded) -> None:
        headers = login(seeded)
        body = [
            {"weekday": 1, "starts": "09:30", "ends": "11:00"},
            {"weekday": 1, "starts": "10:00", "ends": "12:00"},
        ]
        response = seeded.put("/api/v1/resources/1/windows", json=body, headers=headers)
        assert response.status_code == 409

    def test_put_bad_entry_422(self, seeded) -> None:
        headers = login(seeded)
        body = [{"weekday": 9, "starts": "09:30", "ends": "10:00"}]
        assert (
            seeded.put("/api/v1/resources/1/windows", json=body, headers=headers).status_code == 422
        )


class TestExceptions:
    def test_create_valid(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-25",
                "endDate": "2022-12-25",
                "kind": "closed",
                "reason": "Christmas",
            },
            headers=headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["startDate"] == "2022-12-25"
        assert body["endDate"] == "2022-12-25"
        assert body["kind"] == "closed"

    def test_create_inverted_range_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-26",
                "endDate": "2022-12-25",
                "kind": "closed",
            },
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_invalid_kind_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-25",
                "endDate": "2022-12-25",
                "kind": "maybe",
            },
            headers=headers,
        )
        assert response.status_code == 422

    def test_create_overlapping_range_409(self, seeded) -> None:
        headers = login(seeded)
        seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-20",
                "endDate": "2022-12-27",
                "kind": "closed",
            },
            headers=headers,
        )
        response = seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-25",
                "endDate": "2022-12-26",
                "kind": "open",
            },
            headers=headers,
        )
        assert response.status_code == 409

    def test_list_and_delete(self, seeded) -> None:
        headers = login(seeded)
        created = seeded.post(
            "/api/v1/availability-exceptions",
            json={
                "resourceId": 1,
                "startDate": "2022-12-25",
                "endDate": "2022-12-25",
                "kind": "closed",
            },
            headers=headers,
        ).json()
        listing = seeded.get("/api/v1/availability-exceptions")
        assert len(listing.json()) == 1
        assert (
            seeded.delete(
                f"/api/v1/availability-exceptions/{created['id']}", headers=headers
            ).status_code
            == 204
        )
        assert seeded.get("/api/v1/availability-exceptions").json() == []

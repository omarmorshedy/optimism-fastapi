"""API contract tests for /api/v1/resources (API_SPEC §3.1, §4.2).

Ports the legacy CRUD matrix from legacy/api/test/integration/general.js with
the improvements applied (per the parity matrix, API_SPEC §10): writes are
admin-only + CSRF, validation errors are 422, missing deletes are 404, and
responses carry the Resource shape.
"""

from __future__ import annotations

import pytest

from tests.conftest import login

RESOURCE_PAYLOAD = {"resourceTypeId": 1, "name": "Test", "capacity": 123}


@pytest.fixture()
def seeded(admin_client, db_session):
    """Seed one resource type and one resource via the database."""
    from tests.factories import create_resource, create_resource_type

    resource_type = create_resource_type(db_session, name="room")
    create_resource(db_session, name="Test", capacity=123, resource_type_id=resource_type.id)
    db_session.commit()
    return admin_client


class TestPublicReads:
    def test_list_resources_empty(self, client) -> None:
        response = client.get("/api/v1/resources")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_resources_ordered_by_id(self, admin_client, db_session) -> None:
        from tests.factories import create_resource

        create_resource(db_session, name="Alpha", capacity=1)
        create_resource(db_session, name="Beta", capacity=2)
        db_session.commit()
        response = admin_client.get("/api/v1/resources")
        assert response.status_code == 200
        names = [r["name"] for r in response.json()]
        assert names == ["Alpha", "Beta"]

    def test_get_resource_valid(self, seeded) -> None:
        response = seeded.get("/api/v1/resources/1")
        assert response.status_code == 200
        assert response.json() == {
            "id": 1,
            "resourceTypeId": 1,
            "name": "Test",
            "capacity": 123,
        }

    def test_get_resource_invalid_id_is_422(self, seeded) -> None:
        response = seeded.get("/api/v1/resources/-1")
        assert response.status_code == 422
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["type"].endswith("/validation")

    def test_get_resource_nonexistent_is_404(self, seeded) -> None:
        response = seeded.get("/api/v1/resources/9999")
        assert response.status_code == 404
        body = response.json()
        assert body["type"].endswith("/not-found")
        assert body["detail"] == "Resource not found."


class TestAdminWrites:
    def test_create_requires_auth(self, client) -> None:
        response = client.post("/api/v1/resources", json=RESOURCE_PAYLOAD)
        assert response.status_code == 401

    def test_create_requires_csrf(self, client) -> None:
        login(client)
        response = client.post("/api/v1/resources", json=RESOURCE_PAYLOAD)
        assert response.status_code == 403

    def test_create_valid(self, admin_client, db_session) -> None:
        from tests.factories import create_resource_type

        create_resource_type(db_session, name="room")
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.post("/api/v1/resources", json=RESOURCE_PAYLOAD, headers=headers)
        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "Test"
        assert body["capacity"] == 123
        assert body["resourceTypeId"] == 1
        assert body["id"] == 1
        # Created item is fetchable.
        fetched = admin_client.get("/api/v1/resources/1")
        assert fetched.status_code == 200

    def test_create_missing_field_is_422(self, admin_client, db_session) -> None:
        from tests.factories import create_resource_type

        create_resource_type(db_session, name="room")
        db_session.commit()
        headers = login(admin_client)
        payload = dict(RESOURCE_PAYLOAD)
        del payload["capacity"]
        response = admin_client.post("/api/v1/resources", json=payload, headers=headers)
        assert response.status_code == 422

    def test_create_with_id_field_is_422(self, admin_client) -> None:
        headers = login(admin_client)
        payload = {**RESOURCE_PAYLOAD, "id": 5}
        response = admin_client.post("/api/v1/resources", json=payload, headers=headers)
        assert response.status_code == 422

    def test_create_with_extra_field_is_422(self, admin_client) -> None:
        headers = login(admin_client)
        payload = {**RESOURCE_PAYLOAD, "shouldNot": "be here"}
        response = admin_client.post("/api/v1/resources", json=payload, headers=headers)
        assert response.status_code == 422

    def test_create_blank_name_is_422(self, admin_client) -> None:
        headers = login(admin_client)
        payload = {**RESOURCE_PAYLOAD, "name": "   "}
        response = admin_client.post("/api/v1/resources", json=payload, headers=headers)
        assert response.status_code == 422

    def test_create_duplicate_name_is_409(self, admin_client, db_session) -> None:
        from tests.factories import create_resource, create_resource_type

        create_resource_type(db_session, name="room")
        create_resource(db_session, name="Test", capacity=1)
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.post("/api/v1/resources", json=RESOURCE_PAYLOAD, headers=headers)
        assert response.status_code == 409
        assert response.json()["type"].endswith("/conflict")

    def test_create_unknown_resource_type_is_404(self, admin_client) -> None:
        headers = login(admin_client)
        payload = {**RESOURCE_PAYLOAD, "resourceTypeId": 9999}
        response = admin_client.post("/api/v1/resources", json=payload, headers=headers)
        assert response.status_code == 404

    def test_update_valid(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put(
            "/api/v1/resources/1",
            json={"name": "Updated in test method"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated in test method"
        fetched = seeded.get("/api/v1/resources/1")
        assert fetched.json()["name"] == "Updated in test method"

    def test_update_no_id_in_body_ok(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put("/api/v1/resources/1", json={"name": "NoId"}, headers=headers)
        assert response.status_code == 200

    def test_update_mismatched_id_is_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put("/api/v1/resources/1", json={"id": 2, "name": "X"}, headers=headers)
        assert response.status_code == 422

    def test_update_invalid_id_is_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put("/api/v1/resources/-1", json={"name": "X"}, headers=headers)
        assert response.status_code == 422

    def test_update_nonexistent_is_404(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put("/api/v1/resources/9999", json={"name": "X"}, headers=headers)
        assert response.status_code == 404

    def test_update_duplicate_name_is_409(self, admin_client, db_session) -> None:
        from tests.factories import create_resource

        create_resource(db_session, name="Alpha", capacity=1)
        create_resource(db_session, name="Beta", capacity=1)
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.put("/api/v1/resources/1", json={"name": "Beta"}, headers=headers)
        assert response.status_code == 409

    def test_delete_valid_returns_204(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.delete("/api/v1/resources/1", headers=headers)
        assert response.status_code == 204
        assert seeded.get("/api/v1/resources/1").status_code == 404

    def test_delete_nonexistent_is_404(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.delete("/api/v1/resources/9999", headers=headers)
        assert response.status_code == 404

    def test_delete_invalid_id_is_422(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.delete("/api/v1/resources/-1", headers=headers)
        assert response.status_code == 422

    def test_delete_blocked_with_active_bookings_is_409(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource, create_window

        resource = create_resource(db_session, name="Busy", capacity=1)
        create_window(db_session, resource.id)
        create_booking(
            db_session,
            resource.id,
            __import__("datetime").datetime(
                2030, 1, 7, 9, 30, tzinfo=__import__("datetime").timezone.utc
            ),
            __import__("datetime").datetime(
                2030, 1, 7, 10, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        )
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.delete(f"/api/v1/resources/{resource.id}", headers=headers)
        assert response.status_code == 409

    def test_delete_with_only_cancelled_bookings_succeeds(self, admin_client, db_session) -> None:
        from tests.factories import create_booking, create_resource, create_window

        resource = create_resource(db_session, name="Quiet", capacity=1)
        create_window(db_session, resource.id)
        create_booking(
            db_session,
            resource.id,
            __import__("datetime").datetime(
                2030, 1, 7, 9, 30, tzinfo=__import__("datetime").timezone.utc
            ),
            __import__("datetime").datetime(
                2030, 1, 7, 10, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            cancelled=True,
        )
        db_session.commit()
        headers = login(admin_client)
        response = admin_client.delete(f"/api/v1/resources/{resource.id}", headers=headers)
        assert response.status_code == 204

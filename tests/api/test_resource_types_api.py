"""API contract tests for /api/v1/resource-types (API_SPEC §3.2, §4.3)."""

from __future__ import annotations

import pytest

from tests.conftest import login


@pytest.fixture()
def seeded(admin_client, db_session):
    from tests.factories import create_resource_type

    create_resource_type(db_session, name="room")
    db_session.commit()
    return admin_client


class TestPublicReads:
    def test_list(self, client) -> None:
        assert client.get("/api/v1/resource-types").json() == []

    def test_list_ordered(self, seeded) -> None:
        response = seeded.get("/api/v1/resource-types")
        assert response.status_code == 200
        assert [t["name"] for t in response.json()] == ["room"]

    def test_get_valid(self, seeded) -> None:
        response = seeded.get("/api/v1/resource-types/1")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "name": "room"}

    def test_get_invalid_id_422(self, seeded) -> None:
        assert seeded.get("/api/v1/resource-types/-1").status_code == 422

    def test_get_nonexistent_404(self, seeded) -> None:
        response = seeded.get("/api/v1/resource-types/9999")
        assert response.status_code == 404


class TestAdminWrites:
    def test_create_requires_auth(self, client) -> None:
        assert (
            client.post("/api/v1/resource-types", json={"name": "laser-cutter"}).status_code == 401
        )

    def test_create_requires_csrf(self, client) -> None:
        login(client)
        assert (
            client.post("/api/v1/resource-types", json={"name": "laser-cutter"}).status_code == 403
        )

    def test_create_valid(self, admin_client) -> None:
        headers = login(admin_client)
        response = admin_client.post(
            "/api/v1/resource-types", json={"name": "laser-cutter"}, headers=headers
        )
        assert response.status_code == 201
        assert response.json() == {"id": 1, "name": "laser-cutter"}

    def test_create_missing_field_422(self, admin_client) -> None:
        headers = login(admin_client)
        assert (
            admin_client.post("/api/v1/resource-types", json={}, headers=headers).status_code == 422
        )

    def test_create_extra_field_422(self, admin_client) -> None:
        headers = login(admin_client)
        assert (
            admin_client.post(
                "/api/v1/resource-types", json={"name": "x", "surprise": 1}, headers=headers
            ).status_code
            == 422
        )

    def test_create_blank_name_422(self, admin_client) -> None:
        headers = login(admin_client)
        assert (
            admin_client.post(
                "/api/v1/resource-types", json={"name": "  "}, headers=headers
            ).status_code
            == 422
        )

    def test_create_duplicate_409(self, admin_client, db_session) -> None:
        from tests.factories import create_resource_type

        create_resource_type(db_session, name="room")
        db_session.commit()
        headers = login(admin_client)
        assert (
            admin_client.post(
                "/api/v1/resource-types", json={"name": "room"}, headers=headers
            ).status_code
            == 409
        )

    def test_update_valid(self, seeded) -> None:
        headers = login(seeded)
        response = seeded.put(
            "/api/v1/resource-types/1", json={"name": "big-room"}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["name"] == "big-room"

    def test_update_nonexistent_404(self, seeded) -> None:
        headers = login(seeded)
        assert (
            seeded.put(
                "/api/v1/resource-types/9999", json={"name": "x"}, headers=headers
            ).status_code
            == 404
        )

    def test_update_duplicate_409(self, admin_client, db_session) -> None:
        from tests.factories import create_resource_type

        create_resource_type(db_session, name="room")
        create_resource_type(db_session, name="laser")
        db_session.commit()
        headers = login(admin_client)
        assert (
            admin_client.put(
                "/api/v1/resource-types/2", json={"name": "room"}, headers=headers
            ).status_code
            == 409
        )

    def test_delete_valid_204(self, seeded) -> None:
        headers = login(seeded)
        assert seeded.delete("/api/v1/resource-types/1", headers=headers).status_code == 204
        assert seeded.get("/api/v1/resource-types/1").status_code == 404

    def test_delete_nonexistent_404(self, seeded) -> None:
        headers = login(seeded)
        assert seeded.delete("/api/v1/resource-types/9999", headers=headers).status_code == 404

    def test_delete_nulls_resource_type_id_on_resources(self, admin_client, db_session) -> None:
        """Legacy semantics kept (§11.5): deleting a type nulls resourceTypeId."""
        from tests.factories import create_resource, create_resource_type

        resource_type = create_resource_type(db_session, name="room")
        create_resource(db_session, name="Dinky", capacity=1, resource_type_id=resource_type.id)
        db_session.commit()
        headers = login(admin_client)
        assert admin_client.delete("/api/v1/resource-types/1", headers=headers).status_code == 204
        resource = admin_client.get("/api/v1/resources/1").json()
        assert resource["resourceTypeId"] is None

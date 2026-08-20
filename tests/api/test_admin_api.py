"""API contract tests for admin auth (API_SPEC §4.1, ADR-005) and audit events."""

from __future__ import annotations

from tests.conftest import TEST_PASSWORD, login


class TestLogin:
    def test_login_success_sets_cookies(self, client) -> None:
        response = client.post("/api/v1/admin/login", json={"password": TEST_PASSWORD})
        assert response.status_code == 200
        assert response.json() == {"message": "Logged in."}
        assert "optimism_admin_session" in client.cookies
        assert "csrf_token" in client.cookies

    def test_login_wrong_password_401(self, client) -> None:
        response = client.post("/api/v1/admin/login", json={"password": "wrong"})
        assert response.status_code == 401
        assert response.json()["type"].endswith("/unauthorized")

    def test_login_missing_field_422(self, client) -> None:
        assert client.post("/api/v1/admin/login", json={}).status_code == 422

    def test_login_extra_field_422(self, client) -> None:
        assert (
            client.post("/api/v1/admin/login", json={"password": "x", "user": "y"}).status_code
            == 422
        )

    def test_login_rate_limited(self, db_session, settings) -> None:
        from app.core.config import Settings
        from app.core.security import hash_password
        from app.db.base import Base
        from app.db.engine import get_engine
        from app.main import create_app
        from fastapi.testclient import TestClient
        from sqlalchemy import text

        limited = Settings(
            database_url="sqlite:///:memory:",
            auto_migrate=False,
            email_worker_enabled=False,
            admin_password_hash=hash_password("test-password"),
            session_secret="s" * 32,
            environment="test",
            rate_limit_admin_login="2/minute",
            smtp_host="",
        )
        engine = get_engine(limited)
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
        app = create_app(limited)
        with TestClient(app) as client:
            assert client.post("/api/v1/admin/login", json={"password": "x"}).status_code == 401
            assert client.post("/api/v1/admin/login", json={"password": "x"}).status_code == 401
            assert client.post("/api/v1/admin/login", json={"password": "x"}).status_code == 429


class TestLogout:
    def test_logout_revokes_session(self, client) -> None:
        login(client)
        assert client.get("/api/v1/availability-windows").status_code == 200
        response = client.post(
            "/api/v1/admin/logout", headers={"X-CSRF-Token": client.cookies.get("csrf_token")}
        )
        assert response.status_code == 204
        # The session cookie is deleted; further admin calls are 401.
        assert client.get("/api/v1/availability-windows").status_code == 401

    def test_logout_requires_csrf(self, client) -> None:
        login(client)
        assert client.post("/api/v1/admin/logout").status_code == 403

    def test_logout_requires_auth(self, client) -> None:
        assert client.post("/api/v1/admin/logout").status_code == 401


class TestAudit:
    def test_admin_actions_are_audited(self, admin_client, db_session) -> None:
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        headers = login(admin_client)
        admin_client.post("/api/v1/resource-types", json={"name": "room"}, headers=headers)
        admin_client.post(
            "/api/v1/resources",
            json={"name": "Dinky", "capacity": 1, "resourceTypeId": 1},
            headers=headers,
        )
        db_session.expire_all()
        events = list(db_session.scalars(select(AuditEvent).order_by(AuditEvent.id)))
        assert [e.action for e in events] == ["resource_type.create", "resource.create"]
        assert all(e.actor == "shared_admin" for e in events)
        assert all(e.outcome == "success" for e in events)
        assert events[1].resource_id == 1

    def test_public_actions_are_not_audited(self, admin_client, db_session) -> None:
        from app.models.audit_event import AuditEvent
        from sqlalchemy import select

        from tests.factories import create_resource, create_window

        create_resource(db_session, name="Dinky", capacity=1)
        create_window(db_session, 1)
        db_session.commit()
        # Public booking creation (token-authenticated) is not an admin action.
        admin_client.post(
            "/api/v1/bookings",
            json={
                "resourceId": 1,
                "email": "a@b.org",
                "name": "A",
                "notes": "",
                "starts": "2030-01-07T09:30:00",
                "ends": "2030-01-07T10:30:00",
            },
        )
        db_session.expire_all()
        assert list(db_session.scalars(select(AuditEvent))) == []

"""Shared pytest fixtures.

Uses an in-memory SQLite database with a StaticPool so every request thread
shares one connection. This is a test convenience (ADR-003: PostgreSQL is the
real target; integration tests under tests/integration exercise PostgreSQL).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.engine import get_engine, get_session_factory
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

TEST_PASSWORD = "test-password"
ADMIN_HASH = hash_password(TEST_PASSWORD)

# All tables in FK-safe deletion order.
TABLE_NAMES = [
    "audit_events",
    "admin_sessions",
    "email_outbox",
    "bookings",
    "availability_exceptions",
    "availability_windows",
    "resources",
    "resource_types",
]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        auto_migrate=False,
        email_worker_enabled=False,
        admin_password_hash=ADMIN_HASH,
        session_secret="test-secret-test-secret-test-secret!",
        environment="test",
        rate_limit_booking_create="100000/minute",
        rate_limit_booking_cancel="100000/minute",
        rate_limit_calendar_read="100000/minute",
        rate_limit_admin_login="100000/minute",
        smtp_host="",
    )


@pytest.fixture(scope="session")
def engine(settings):
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        conn.execute(text("INSERT OR IGNORE INTO alembic_version (version_num) VALUES ('0001')"))
    return engine


@pytest.fixture()
def db_session(engine, settings) -> Iterator[Session]:
    factory = get_session_factory(settings)
    session = factory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_tables(engine) -> Iterator[None]:
    """Truncate all tables before each test (fresh, deterministic state)."""
    with engine.begin() as conn:
        for table in TABLE_NAMES:
            conn.execute(text(f"DELETE FROM {table}"))
    yield


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_client(client, settings):
    """A TestClient already logged in as the shared admin (with CSRF cookie)."""
    response = client.post("/api/v1/admin/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 200, response.text
    return client


def login(client: TestClient, password: str = TEST_PASSWORD) -> dict[str, str]:
    """Log in and return headers carrying the CSRF token for API writes."""
    response = client.post("/api/v1/admin/login", json={"password": password})
    assert response.status_code == 200, response.text
    csrf = client.cookies.get("csrf_token")
    assert csrf
    return {"X-CSRF-Token": csrf}

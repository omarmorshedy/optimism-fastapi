"""PostgreSQL integration tests (ADR-003).

These exercise real PostgreSQL semantics: Alembic migrations (including the
GiST exclusion constraint), advisory-lock concurrency (no overbooking), and
timestamptz round-trips. They are skipped unless a PostgreSQL server is
reachable (set TEST_DATABASE_URL, e.g.
postgresql+psycopg://optimism:optimism@localhost:5432/optimism_test).
"""

from __future__ import annotations

import datetime as dt
import os
import threading

import pytest
from app.core.config import Settings
from app.core.exceptions import Problem
from app.core.security import hash_password
from app.db.engine import get_engine, get_session_factory, session_scope
from app.domains.bookings.schemas import BookingCreate
from sqlalchemy import text

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://optimism:optimism@localhost:5432/optimism_test"
)


def _pg_reachable(url: str) -> bool:
    try:
        engine = get_engine(Settings(database_url=url, _env_file=None))
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_reachable(TEST_DATABASE_URL)
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_AVAILABLE, reason="PostgreSQL not reachable"),
]


@pytest.fixture(scope="module")
def pg_settings() -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        auto_migrate=False,
        email_worker_enabled=False,
        admin_password_hash=hash_password("test-password"),
        session_secret="s" * 32,
        environment="test",
        smtp_host="",
    )


@pytest.fixture(scope="module")
def migrated_db(pg_settings):
    """Run the Alembic migration chain from scratch (upgrade + downgrade + upgrade)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "app/migrations")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield pg_settings
    command.downgrade(cfg, "base")


class TestMigration:
    def test_schema_created(self, migrated_db) -> None:
        engine = get_engine(migrated_db)
        with engine.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            }
        assert {
            "resource_types",
            "resources",
            "availability_windows",
            "bookings",
            "email_outbox",
            "admin_sessions",
            "audit_events",
        } <= tables

    def test_exclusion_constraint_blocks_overlap(self, migrated_db) -> None:
        """The GiST exclusion constraint rejects overlapping windows for the
        same resource+weekday at the database level (ADR-008 safety net)."""
        factory = get_session_factory(migrated_db)
        with factory() as session:
            resource_id = session.execute(
                text("INSERT INTO resources (name, capacity) VALUES ('R', 1) RETURNING id")
            ).scalar()
            session.commit()
            session.execute(
                text(
                    "INSERT INTO availability_windows (resource_id, weekday, starts, ends) "
                    "VALUES (:rid, 1, '09:30', '11:00')"
                ),
                {"rid": resource_id},
            )
            session.commit()
            with pytest.raises(Exception):  # noqa: B017 - any integrity error means the constraint fired
                session.execute(
                    text(
                        "INSERT INTO availability_windows (resource_id, weekday, starts, ends) "
                        "VALUES (:rid, 1, '10:00', '12:00')"
                    ),
                    {"rid": resource_id},
                )
                session.commit()

    def test_touching_windows_allowed(self, migrated_db) -> None:
        factory = get_session_factory(migrated_db)
        with factory() as session:
            resource_id = session.execute(
                text("INSERT INTO resources (name, capacity) VALUES ('R2', 1) RETURNING id")
            ).scalar()
            session.execute(
                text(
                    "INSERT INTO availability_windows (resource_id, weekday, starts, ends) "
                    "VALUES (:rid, 1, '09:30', '11:00')"
                ),
                {"rid": resource_id},
            )
            session.execute(
                text(
                    "INSERT INTO availability_windows (resource_id, weekday, starts, ends) "
                    "VALUES (:rid, 1, '11:00', '12:00')"
                ),
                {"rid": resource_id},
            )
            session.commit()

    def test_timestamptz_roundtrip_utc(self, migrated_db) -> None:
        factory = get_session_factory(migrated_db)
        value = dt.datetime(2022, 3, 17, 9, 30, tzinfo=dt.UTC)
        with factory() as session:
            resource_id = session.execute(
                text("INSERT INTO resources (name, capacity) VALUES ('R3', 1) RETURNING id")
            ).scalar()
            session.execute(
                text(
                    "INSERT INTO bookings (resource_id, email, name, notes, starts, ends, cancelled) "
                    "VALUES (:rid, 'a@b.org', 'N', '', :starts, :starts + interval '1 hour', false)"
                ),
                {"rid": resource_id, "starts": value},
            )
            session.commit()
            returned = session.execute(
                text("SELECT starts FROM bookings WHERE email = 'a@b.org'")
            ).scalar()
        assert returned == value
        assert returned.tzinfo is not None  # timestamptz stays aware


class TestConcurrency:
    def test_no_overbooking_under_concurrency(self, migrated_db) -> None:
        """capacity = 1; 10 parallel creations for the same window must yield
        exactly 1 success and 9 conflicts (ADR-006)."""
        factory = get_session_factory(migrated_db)
        with factory() as session:
            resource_id = session.execute(
                text("INSERT INTO resources (name, capacity) VALUES ('Hot', 1) RETURNING id")
            ).scalar()
            session.execute(
                text(
                    "INSERT INTO availability_windows (resource_id, weekday, starts, ends) "
                    "VALUES (:rid, 1, '09:30', '10:30')"
                ),
                {"rid": resource_id},
            )
            session.commit()

        payload = BookingCreate(
            resource_id=resource_id,
            email="someone@example.org",
            name="A Name",
            notes="",
            starts="2030-01-07T09:30:00",
            ends="2030-01-07T10:30:00",
        )

        results: list[str] = []
        lock = threading.Lock()

        def worker() -> None:
            try:
                with session_scope(migrated_db) as session:
                    from app.domains.bookings.service import BookingService

                    BookingService(session, migrated_db).create(payload)
                    session.commit()
                outcome = "created"
            except Problem as exc:
                outcome = f"conflict:{exc.type_suffix}"
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
            with lock:
                results.append(outcome)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count("created") == 1, results
        assert results.count("conflict:conflict") == 9, results

        # And the calendar confirms exactly one booking.
        from app.domains.calendar.service import CalendarService

        assert resource_id is not None
        with session_scope(migrated_db) as session:
            calendar = CalendarService(session).get(
                dt.date(2030, 1, 7), dt.date(2030, 1, 8), resource_id
            )
        slot = calendar["dates"][0]["resources"][0]["slots"][0]
        assert slot["status"] == "unavailable"

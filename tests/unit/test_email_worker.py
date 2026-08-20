"""Unit tests for the email outbox worker (ADR-010, decision #13)."""

from __future__ import annotations

import datetime as dt

import pytest
from app.core.config import Settings
from app.core.time import utcnow
from app.db.engine import get_session_factory
from app.domains.bookings.repository import EmailOutboxRepository
from app.domains.bookings.worker import EmailWorker
from app.integrations.email.provider import NullEmailProvider

from tests.factories import create_booking, create_resource


@pytest.fixture()
def worker_settings(settings) -> Settings:
    return Settings(
        database_url=settings.database_url,
        auto_migrate=False,
        email_worker_enabled=True,
        admin_password_hash=settings.admin_password_hash,
        session_secret=settings.session_secret,
        environment="test",
        smtp_host="",
        email_worker_poll_seconds=1,
        email_retry_base_delay_seconds=0,
        email_retry_max_attempts=3,
        email_retry_max_delay_seconds=4,
        email_worker_alive_timeout_seconds=60,
    )


@pytest.fixture()
def outbox_entry(settings, db_session):
    create_resource(db_session, name="Dinky", capacity=1)
    booking = create_booking(
        db_session,
        1,
        dt.datetime(2030, 1, 7, 9, 30, tzinfo=dt.UTC),
        dt.datetime(2030, 1, 7, 10, 30, tzinfo=dt.UTC),
    )
    db_session.flush()
    repo = EmailOutboxRepository(db_session)
    entry = repo.enqueue(
        booking_id=booking.id,
        subject="Booking Confirmation - Dinky",
        body="Welcome!",
        from_addr="booking@example.org",
        to_addr=booking.email,
        bcc_addr="organisers@example.org",
    )
    db_session.commit()
    return entry.id


class TestEmailWorker:
    def test_sends_pending_email(self, worker_settings, outbox_entry) -> None:
        provider = NullEmailProvider()
        worker = EmailWorker(worker_settings, provider)
        processed = worker.poll_once()
        assert processed == 1
        assert provider.sent
        assert provider.sent[0]["to"] == "someone@example.org"
        assert provider.sent[0]["subject"] == "Booking Confirmation - Dinky"
        assert provider.sent[0]["bcc"] == "organisers@example.org"

        factory = get_session_factory(worker_settings)
        session = factory()
        entry = session.get(
            __import__("app.models.email_outbox", fromlist=["EmailOutbox"]).EmailOutbox,
            outbox_entry,
        )
        assert entry is not None
        assert entry.status == "sent"
        assert entry.attempts == 0
        session.close()

    def test_idle_poll_returns_zero(self, worker_settings) -> None:
        worker = EmailWorker(worker_settings, NullEmailProvider())
        assert worker.poll_once() == 0

    def test_failure_retries_then_dead_letters(self, worker_settings, outbox_entry) -> None:
        class AlwaysFails:
            def send(self, **kwargs) -> None:
                raise RuntimeError("SMTP down")

        worker: EmailWorker = EmailWorker(worker_settings, AlwaysFails())
        import time

        for _ in range(4):
            worker.poll_once()
            time.sleep(1.1)  # let the back-off become due (second-precision SQLite clock)

        factory = get_session_factory(worker_settings)
        session = factory()
        from app.models.email_outbox import EmailOutbox

        entry = session.get(EmailOutbox, outbox_entry)
        assert entry is not None
        assert entry.status == "dead_letter"
        assert entry.attempts == 3
        session.close()

    def test_failure_backoff_schedules_next_attempt(self, worker_settings, outbox_entry) -> None:
        class AlwaysFails:
            def send(self, **kwargs) -> None:
                raise RuntimeError("SMTP down")

        worker: EmailWorker = EmailWorker(worker_settings, AlwaysFails())
        worker.poll_once()

        factory = get_session_factory(worker_settings)
        session = factory()
        from app.models.email_outbox import EmailOutbox

        entry = session.get(EmailOutbox, outbox_entry)
        assert entry is not None
        assert entry.status == "failed"
        assert entry.attempts == 1
        # Back-off = base * 2^0 = 1s after now.
        from app.core.time import ensure_utc

        next_attempt = ensure_utc(entry.next_attempt_at)
        assert next_attempt is not None
        assert (next_attempt - utcnow()).total_seconds() <= 2
        session.close()

    def test_heartbeat_alive_after_poll(self, worker_settings) -> None:
        worker = EmailWorker(worker_settings, NullEmailProvider())
        assert not worker.is_alive()  # never polled
        worker.poll_once()
        assert worker.is_alive()

    def test_start_stop_lifecycle(self, worker_settings, outbox_entry) -> None:
        worker = EmailWorker(worker_settings, NullEmailProvider())
        worker.start()
        import time

        time.sleep(0.2)
        assert worker.is_alive()
        worker.stop()
        assert not worker.is_alive()

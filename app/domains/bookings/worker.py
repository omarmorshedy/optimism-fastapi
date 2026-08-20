"""Email outbox worker (ADR-010, decision #13).

Polls ``email_outbox`` on an interval, sends via the provider, applies
exponential back-off on failure (base 60s, doubled each attempt, capped at 960s, max 5 attempts),
and moves entries to ``dead_letter`` after the final failure with an alert
(log + metric). Uses ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so multiple
workers cannot double-send.
"""

from __future__ import annotations

import datetime as dt
import threading

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import EMAIL_OUTBOX_PENDING, EMAIL_SENT, EMAIL_WORKER_ALIVE
from app.core.time import utcnow
from app.db.engine import session_scope
from app.domains.bookings.repository import EmailOutboxRepository
from app.integrations.email.provider import EmailProvider

logger = get_logger("optimism.email_worker")


class EmailWorker:
    def __init__(self, settings: Settings, provider: EmailProvider) -> None:
        self.settings = settings
        self.provider = provider
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat: dt.datetime | None = None
        self._lock = threading.Lock()

    # --- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="email-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        # A stopped worker must not report ready.
        with self._lock:
            self._heartbeat = None
        EMAIL_WORKER_ALIVE.set(0)

    def is_alive(self) -> bool:
        with self._lock:
            heartbeat = self._heartbeat
        if heartbeat is None:
            return False
        return (
            utcnow() - heartbeat
        ).total_seconds() <= self.settings.email_worker_alive_timeout_seconds

    # --- internals -----------------------------------------------------------

    def _run(self) -> None:
        logger.info("email_worker_started")
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                logger.exception("email_worker_poll_error")
            self._stop_event.wait(self.settings.email_worker_poll_seconds)

    def poll_once(self) -> int:
        """Process one batch of pending emails; returns the number handled."""
        with self._lock:
            self._heartbeat = utcnow()
        EMAIL_WORKER_ALIVE.set(1)

        processed = 0
        with session_scope(self.settings) as session:
            repo = EmailOutboxRepository(session)
            EMAIL_OUTBOX_PENDING.set(repo.pending_count())
            dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
            entries = repo.claim_batch(for_update=(dialect == "postgresql"))
            if not entries:
                session.commit()
                return 0

            for entry in entries:
                processed += 1
                try:
                    self.provider.send(
                        from_addr=entry.from_addr,
                        to_addr=entry.to_addr,
                        bcc_addr=entry.bcc_addr,
                        subject=entry.subject,
                        body=entry.body,
                    )
                    repo.mark_sent(entry)
                    EMAIL_SENT.labels(status="sent").inc()
                    logger.info(
                        "email_sent",
                        outbox_id=entry.id,
                        booking_id=entry.booking_id,
                    )
                except Exception as exc:
                    attempts = entry.attempts + 1
                    repo.record_failure(entry, str(exc), attempts=attempts)
                    if attempts >= self.settings.email_retry_max_attempts:
                        repo.mark_dead_letter(entry)
                        EMAIL_SENT.labels(status="dead_letter").inc()
                        logger.error(
                            "email_dead_letter",
                            outbox_id=entry.id,
                            booking_id=entry.booking_id,
                            attempts=attempts,
                            error=str(exc),
                        )
                    else:
                        entry.status = "failed"
                        delay = min(
                            self.settings.email_retry_base_delay_seconds * (2 ** (attempts - 1)),
                            self.settings.email_retry_max_delay_seconds,
                        )
                        entry.next_attempt_at = utcnow() + dt.timedelta(seconds=delay)
                        EMAIL_SENT.labels(status="failed").inc()
                        logger.warning(
                            "email_retry",
                            outbox_id=entry.id,
                            booking_id=entry.booking_id,
                            attempts=attempts,
                            next_attempt_delay_seconds=delay,
                            error=str(exc),
                        )
            session.commit()
            EMAIL_OUTBOX_PENDING.set(repo.pending_count())
        return processed

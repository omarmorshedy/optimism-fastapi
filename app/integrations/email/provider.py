"""Email provider abstraction (ADR-010).

The worker depends only on this interface, so tests can inject a null provider.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.core.config import Settings


class EmailProvider(Protocol):
    def send(
        self, *, from_addr: str, to_addr: str, bcc_addr: str | None, subject: str, body: str
    ) -> None: ...


class SmtpEmailProvider:
    """SMTP transport with optional STARTTLS and login (arc42 §7.2)."""

    def __init__(self, settings: Settings) -> None:
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_user
        self.password = settings.smtp_pass
        self.use_tls = settings.smtp_tls

    def send(
        self, *, from_addr: str, to_addr: str, bcc_addr: str | None, subject: str, body: str
    ) -> None:
        message = EmailMessage()
        message["From"] = from_addr
        message["To"] = to_addr
        if bcc_addr:
            message["Bcc"] = bcc_addr
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.ehlo()
            if self.use_tls:
                smtp.starttls()
                smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class NullEmailProvider:
    """No-op provider for tests and environments without SMTP configured."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def send(
        self, *, from_addr: str, to_addr: str, bcc_addr: str | None, subject: str, body: str
    ) -> None:
        self.sent.append(
            {
                "from": from_addr,
                "to": to_addr,
                "bcc": bcc_addr or "",
                "subject": subject,
                "body": body,
            }
        )

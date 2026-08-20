"""Repository for admin sessions and audit events."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.admin_session import AdminSession
from app.models.audit_event import AuditEvent


class AdminSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, token_hash: str, expires_at: dt.datetime) -> AdminSession:
        obj = AdminSession(token_hash=token_hash, expires_at=expires_at)
        self.session.add(obj)
        return obj

    def get_by_token_hash(self, token_hash: str) -> AdminSession | None:
        stmt = select(AdminSession).where(AdminSession.token_hash == token_hash)
        return self.session.scalar(stmt)

    def touch(self, obj: AdminSession) -> None:
        obj.last_used_at = dt.datetime.now(dt.UTC)

    def delete(self, obj: AdminSession) -> None:
        self.session.delete(obj)

    def delete_expired(self, now: dt.datetime) -> int:
        result = self.session.execute(delete(AdminSession).where(AdminSession.expires_at < now))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


class AuditEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        action: str,
        outcome: str = "success",
        resource_id: int | None = None,
        booking_id: int | None = None,
        details: dict[str, Any] | None = None,
        actor: str = "shared_admin",
    ) -> AuditEvent:
        obj = AuditEvent(
            action=action,
            actor=actor,
            resource_id=resource_id,
            booking_id=booking_id,
            outcome=outcome,
            details=details,
        )
        self.session.add(obj)
        return obj

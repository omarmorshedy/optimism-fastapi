"""Audit helper — every admin state change appends an audit_events row
(decision #2: generic ``shared_admin`` actor)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domains.admin.repository import AuditEventRepository


def record_audit(
    session: Session,
    action: str,
    *,
    outcome: str = "success",
    resource_id: int | None = None,
    booking_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    AuditEventRepository(session).record(
        action=action,
        outcome=outcome,
        resource_id=resource_id,
        booking_id=booking_id,
        details=details,
    )
